package main

import (
	"bufio"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"math"
	"math/rand"
	"os"
	"os/exec"
	"runtime"
	"strings"
	"time"

	"github.com/kardianos/service"
)

// errorBody builds a JSON {"error": "..."} payload with proper escaping.
func errorBody(err error) []byte {
	b, _ := json.Marshal(map[string]string{"error": err.Error()})
	return b
}

var version = "dev"

const (
	// After this many consecutive fetch failures, enter hibernate mode.
	hibernateThreshold = 30
	// Maximum backoff duration before hibernate kicks in.
	maxBackoff = 10 * time.Minute
	// How often to checkin while hibernating.
	hibernateCheckinInterval = 10 * time.Minute
)

// backoffDuration returns exponential backoff capped at maxBackoff.
// Formula: min(base * 2^failures, maxBackoff) with ±10% jitter.
func backoffDuration(baseInterval time.Duration, consecutiveFailures int) time.Duration {
	exp := math.Min(float64(consecutiveFailures), 8)
	d := time.Duration(float64(baseInterval) * math.Pow(2, exp))
	if d > maxBackoff {
		d = maxBackoff
	}
	// ±10% jitter
	jitter := time.Duration(float64(d) * (0.1 * (2*rand.Float64() - 1)))
	return d + jitter
}

func main() {
	showVersion := flag.Bool("version", false, "Print version and exit")
	server := flag.String("server", os.Getenv("PLOW_SERVER"), "Plow server URL")
	run := flag.Bool("run", false, "Run the agent (used by service manager or for interactive/Docker mode)")
	svcAction := flag.String("service", "", "Service control: install, uninstall, start, stop, restart, status")
	flag.Parse()

	if *showVersion {
		fmt.Println("plow-agent", version)
		os.Exit(0)
	}

	// --run: run the fetch loop (service manager invokes this, or Docker/interactive use)
	if *run {
		if *server == "" {
			fmt.Fprintln(os.Stderr, "Error: --server or PLOW_SERVER is required with --run")
			flag.Usage()
			os.Exit(1)
		}
		runAgent(*server)
		return
	}

	// --service <action>: power-user service control
	if *svcAction != "" {
		if *svcAction == "status" {
			printServiceStatus(*server)
			return
		}
		// For install, we need the server URL to bake into the service config
		if *svcAction == "install" && *server == "" {
			fmt.Fprintln(os.Stderr, "Error: --server or PLOW_SERVER is required for service install")
			flag.Usage()
			os.Exit(1)
		}
		controlService(*svcAction, *server)
		return
	}

	// No args: friend-friendly interactive install wizard
	installWizard(*server)
}

// runAgent starts the fetch loop, either under the service manager or interactively.
// When running under the service manager, service.Interactive() returns false and
// the kardianos/service framework handles Start/Stop lifecycle.
// When running interactively (Docker, --run from terminal), it runs the same way
// but responds to Ctrl+C via the service framework's console handler.
func runAgent(serverURL string) {
	prg := &plowService{server: serverURL}
	svcCfg := serviceConfig(serverURL)

	s, err := service.New(prg, svcCfg)
	if err != nil {
		log.Fatalf("Failed to create service: %v", err)
	}

	logger, err := s.Logger(nil)
	if err != nil {
		log.Fatalf("Failed to create logger: %v", err)
	}
	prg.logger = logger

	if service.Interactive() {
		log.Printf("plow-agent %s — running interactively (Ctrl+C to stop)", version)
	} else {
		logger.Infof("plow-agent %s — running as system service", version)
	}

	if err := s.Run(); err != nil {
		logger.Errorf("Service exited with error: %v", err)
		os.Exit(1)
	}
}

// controlService sends a control action to the system service manager.
// If the action requires root and we're not root, re-execs via sudo.
func controlService(action, serverURL string) {
	switch action {
	case "install", "uninstall", "start", "stop", "restart":
		// These all need root on macOS/Linux
		if needsElevation() {
			fmt.Println("Service management requires elevated privileges, requesting via sudo...")
			args := []string{"--service", action}
			if serverURL != "" {
				args = append(args, "--server", serverURL)
			}
			os.Exit(reexecWithSudo(args))
		}

		prg := &plowService{}
		svcCfg := serviceConfig(serverURL)

		s, err := service.New(prg, svcCfg)
		if err != nil {
			log.Fatalf("Failed to create service: %v", err)
		}

		// On install, clear any stale service state first. launchd (macOS)
		// throttles services that crash-looped, so a reinstall without
		// bootout first will fail with "Input/output error" on start.
		if action == "install" {
			_ = service.Control(s, "stop")
			_ = service.Control(s, "uninstall")
		}

		err = service.Control(s, action)
		if err != nil {
			log.Fatalf("Failed to %s service: %v", action, err)
		}
		fmt.Printf("Service %sed successfully.\n", action)
		if action == "install" {
			fmt.Println("Run 'plow-agent --service start' to start it, or it will start on next boot.")
		}
	default:
		fmt.Fprintf(os.Stderr, "Unknown service action: %s\n", action)
		fmt.Fprintf(os.Stderr, "Valid actions: install, uninstall, start, stop, restart, status\n")
		os.Exit(1)
	}
}

// printServiceStatus shows the current service status.
func printServiceStatus(serverURL string) {
	prg := &plowService{}
	svcCfg := serviceConfig(serverURL)

	s, err := service.New(prg, svcCfg)
	if err != nil {
		log.Fatalf("Failed to create service: %v", err)
	}

	status, err := s.Status()
	if err != nil {
		fmt.Printf("Service status: unknown (%v)\n", err)
		return
	}
	switch status {
	case service.StatusRunning:
		fmt.Println("Service status: running")
	case service.StatusStopped:
		fmt.Println("Service status: stopped")
	default:
		fmt.Println("Service status: unknown")
	}
}

// installWizard is the friend-friendly path: prompt for config, install as
// a system service, and start it. This runs when the binary is double-clicked
// or invoked with no arguments.
func installWizard(serverURL string) {
	fmt.Println("=== Plow Agent Setup ===")
	fmt.Printf("Version: %s\n", version)
	fmt.Printf("Platform: %s\n", service.Platform())
	fmt.Println()

	// Check if already installed
	prg := &plowService{}
	tmpCfg := serviceConfig("https://plow.jackharrhy.dev")
	s, err := service.New(prg, tmpCfg)
	if err != nil {
		log.Fatalf("Failed to create service: %v", err)
	}
	status, statusErr := s.Status()
	if statusErr == nil {
		// Service exists
		switch status {
		case service.StatusRunning:
			fmt.Println("The plow-agent service is already installed and running.")
			fmt.Println()
			fmt.Println("To manage it:")
			fmt.Println("  plow-agent --service stop       Stop the service")
			fmt.Println("  plow-agent --service restart     Restart the service")
			fmt.Println("  plow-agent --service uninstall   Remove the service")
			fmt.Println("  plow-agent --service status      Check status")
			return
		case service.StatusStopped:
			fmt.Println("The plow-agent service is installed but stopped.")
			fmt.Println()
			if confirm("Start it now?") {
				if needsElevation() {
					os.Exit(reexecWithSudo([]string{"--service", "start"}))
				}
				if err := s.Start(); err != nil {
					fmt.Printf("Failed to start: %v\n", err)
					os.Exit(1)
				}
				fmt.Println("Service started!")
			}
			return
		}
	}

	// Not installed — run the wizard
	fmt.Println("This will install plow-agent as a system service so it runs")
	fmt.Println("automatically in the background, even after reboots.")
	fmt.Println()

	// Get server URL
	if serverURL == "" {
		serverURL = prompt("Server URL", "https://plow.jackharrhy.dev")
	}
	fmt.Printf("Server: %s\n", serverURL)

	// Ensure we have a name and keypair before installing
	// This triggers the interactive name prompt if needed
	fmt.Println()
	fmt.Println("Setting up credentials...")
	cfg := loadOrCreateConfig(serverURL)
	if !cfg.registered {
		register(cfg)
	}
	fmt.Printf("Agent ID: %s\n", cfg.agentID)
	fmt.Printf("Agent name: %s\n", cfg.name)
	fmt.Printf("Config dir: %s\n", cfg.configDir)
	fmt.Println()

	// Install and start the service.
	// If we need root, delegate to `--service install` and `--service start`
	// which handle sudo re-exec themselves.
	if needsElevation() {
		fmt.Println()
		fmt.Println("Installing system service (requires sudo)...")
		code := reexecWithSudo([]string{"--service", "install", "--server", serverURL})
		if code != 0 {
			fmt.Println()
			fmt.Println("You can also run interactively without installing a service:")
			fmt.Printf("  plow-agent --run --server %s\n", serverURL)
			os.Exit(code)
		}
		fmt.Println("Starting service...")
		code = reexecWithSudo([]string{"--service", "start", "--server", serverURL})
		if code != 0 {
			fmt.Println("Try: sudo plow-agent --service start")
			os.Exit(code)
		}
	} else {
		svcCfg := serviceConfig(serverURL)
		s, err = service.New(prg, svcCfg)
		if err != nil {
			log.Fatalf("Failed to create service: %v", err)
		}

		// Clear stale service state before installing (same as controlService)
		_ = service.Control(s, "stop")
		_ = service.Control(s, "uninstall")

		fmt.Println("Installing system service...")
		if err := s.Install(); err != nil {
			fmt.Printf("Failed to install service: %v\n", err)
			fmt.Println()
			fmt.Println("You can also run interactively instead:")
			fmt.Printf("  plow-agent --run --server %s\n", serverURL)
			os.Exit(1)
		}
		fmt.Println("Service installed!")

		fmt.Println("Starting service...")
		if err := s.Start(); err != nil {
			// launchd with KeepAlive may start the service on its own schedule;
			// wait briefly and check if it came up anyway.
			time.Sleep(2 * time.Second)
			if st, serr := s.Status(); serr == nil && st == service.StatusRunning {
				fmt.Println("Service is running.")
			} else {
				fmt.Printf("Failed to start: %v\n", err)
				fmt.Println("Try: plow-agent --service start")
				os.Exit(1)
			}
		}
	}
	fmt.Println()
	fmt.Println("Done! The plow-agent is now running as a system service.")
	fmt.Println("It will start automatically on boot.")
	fmt.Println()
	fmt.Println("Your agent is waiting for approval from the server operator.")
	fmt.Println("Once approved, it will begin collecting plow data automatically.")
	fmt.Println()
	fmt.Println("To check status:     plow-agent --service status")
	fmt.Println("To view logs:        journalctl -u plow-agent -f  (Linux)")
	fmt.Println("                     log show --predicate 'process == \"plow-agent\"' --last 1h  (macOS)")
	fmt.Println("To uninstall:        plow-agent --service uninstall")
}

// needsElevation returns true if the current process is not running as root
// on a platform where service install/uninstall requires it (macOS, Linux).
func needsElevation() bool {
	if runtime.GOOS == "windows" {
		return false // Windows uses UAC, not sudo
	}
	return os.Geteuid() != 0
}

// reexecWithSudo re-executes the current binary via sudo with the given
// arguments. It connects stdin/stdout/stderr so the user sees the sudo
// password prompt and all output. Returns the exit code.
func reexecWithSudo(args []string) int {
	exe, err := os.Executable()
	if err != nil {
		fmt.Fprintf(os.Stderr, "Cannot determine executable path: %v\n", err)
		return 1
	}
	sudoArgs := append([]string{exe}, args...)
	cmd := exec.Command("sudo", sudoArgs...)
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			return exitErr.ExitCode()
		}
		return 1
	}
	return 0
}

// prompt asks the user for input with a default value.
func prompt(label, defaultValue string) string {
	if defaultValue != "" {
		fmt.Printf("%s [%s]: ", label, defaultValue)
	} else {
		fmt.Printf("%s: ", label)
	}
	scanner := bufio.NewScanner(os.Stdin)
	if scanner.Scan() {
		val := strings.TrimSpace(scanner.Text())
		if val != "" {
			return val
		}
	}
	return defaultValue
}

// confirm asks a yes/no question, defaulting to yes.
func confirm(question string) bool {
	fmt.Printf("%s [Y/n]: ", question)
	scanner := bufio.NewScanner(os.Stdin)
	if scanner.Scan() {
		val := strings.TrimSpace(strings.ToLower(scanner.Text()))
		return val == "" || val == "y" || val == "yes"
	}
	return true
}
