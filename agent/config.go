package main

import (
	"bufio"
	"crypto/ecdsa"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"strings"
)

// Config holds the agent's runtime configuration.
type Config struct {
	server     string
	key        *ecdsa.PrivateKey
	agentID    string
	publicPEM  string
	name       string
	registered bool
	configDir  string
}

// configDir returns the configuration directory path.
func getConfigDir() string {
	if dir := os.Getenv("PLOW_DATA_DIR"); dir != "" {
		return dir // Docker mode
	}
	if xdg := os.Getenv("XDG_CONFIG_HOME"); xdg != "" {
		return filepath.Join(xdg, "plow-agent")
	}
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".config", "plow-agent")
}

// isDockerMode returns true if PLOW_DATA_DIR is set.
func isDockerMode() bool {
	return os.Getenv("PLOW_DATA_DIR") != ""
}

// loadOrCreateConfig loads existing config or generates new keys.
func loadOrCreateConfig(server string) *Config {
	dir := getConfigDir()
	keyPath := filepath.Join(dir, "key.pem")
	namePath := filepath.Join(dir, "name")

	cfg := &Config{
		server:    server,
		configDir: dir,
	}

	// Try to load existing key
	if data, err := os.ReadFile(keyPath); err == nil {
		key, err := decodePrivateKeyPEM(data)
		if err != nil {
			log.Fatalf("Failed to parse %s: %v", keyPath, err)
		}
		cfg.key = key
		cfg.registered = true
		log.Printf("Loaded existing key from %s", keyPath)
	} else {
		// Generate new keypair
		if err := os.MkdirAll(dir, 0700); err != nil {
			log.Fatalf("Failed to create config dir %s: %v", dir, err)
		}

		key, err := generateKeypair()
		if err != nil {
			log.Fatalf("Failed to generate keypair: %v", err)
		}
		cfg.key = key
		cfg.registered = false

		pemData, err := encodePrivateKeyPEM(key)
		if err != nil {
			log.Fatalf("Failed to encode private key: %v", err)
		}
		if err := os.WriteFile(keyPath, pemData, 0600); err != nil {
			log.Fatalf("Failed to write %s: %v", keyPath, err)
		}
		log.Printf("Generated new keypair, saved to %s", keyPath)
	}

	// Derive agent ID and public PEM
	pubPEM, err := encodePublicKeyPEM(&cfg.key.PublicKey)
	if err != nil {
		log.Fatalf("Failed to encode public key: %v", err)
	}
	cfg.publicPEM = string(pubPEM)

	agentID, err := agentIDFromPublicKey(&cfg.key.PublicKey)
	if err != nil {
		log.Fatalf("Failed to derive agent ID: %v", err)
	}
	cfg.agentID = agentID
	log.Printf("Agent ID: %s", agentID)

	// Load or get name
	if data, err := os.ReadFile(namePath); err == nil {
		cfg.name = strings.TrimSpace(string(data))
	} else {
		cfg.name = getAgentName()
		if err := os.WriteFile(namePath, []byte(cfg.name+"\n"), 0600); err != nil {
			log.Fatalf("Failed to write %s: %v", namePath, err)
		}
	}
	log.Printf("Agent name: %s", cfg.name)

	return cfg
}

// getAgentName gets the agent name from env or CLI prompt.
func getAgentName() string {
	if name := os.Getenv("PLOW_NAME"); name != "" {
		return name
	}
	if isDockerMode() {
		log.Fatal("PLOW_NAME is required in Docker mode (PLOW_DATA_DIR is set)")
	}
	fmt.Print("Enter a name for this agent: ")
	scanner := bufio.NewScanner(os.Stdin)
	if scanner.Scan() {
		name := strings.TrimSpace(scanner.Text())
		if name != "" {
			return name
		}
	}
	log.Fatal("Agent name is required")
	return ""
}
