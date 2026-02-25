package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"math"
	"math/rand"
	"os"
	"time"
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

func waitForApproval(cfg *Config) Schedule {
	for {
		schedule, status, err := checkin(cfg)
		if err != nil {
			log.Printf("Checkin failed: %v, retrying in 30s", err)
			time.Sleep(30 * time.Second)
			continue
		}
		if status == "approved" {
			return schedule
		}
		log.Printf("Status: %s — waiting for approval (checking every 30s)", status)
		time.Sleep(30 * time.Second)
	}
}

func main() {
	showVersion := flag.Bool("version", false, "Print version and exit")
	server := flag.String("server", os.Getenv("PLOW_SERVER"), "Plow server URL")
	flag.Parse()
	if *showVersion {
		fmt.Println("plow-agent", version)
		os.Exit(0)
	}
	if *server == "" {
		fmt.Fprintln(os.Stderr, "Error: --server or PLOW_SERVER is required")
		flag.Usage()
		os.Exit(1)
	}

	// Load or generate config
	cfg := loadOrCreateConfig(*server)

	// Register if needed (first run)
	if !cfg.registered {
		register(cfg)
	}

	// Checkin loop — wait for approval
	schedule := waitForApproval(cfg)

	// Fetch loop
	log.Printf("Approved! Fetching every %ds (offset %ds)", schedule.IntervalSeconds, schedule.OffsetSeconds)
	time.Sleep(time.Duration(schedule.OffsetSeconds) * time.Second)

	consecutiveFailures := 0
	baseInterval := time.Duration(schedule.IntervalSeconds) * time.Second

	for {
		// Check if we've hit hibernate threshold
		if consecutiveFailures >= hibernateThreshold {
			log.Printf("Hibernating after %d consecutive failures — checking in every %v",
				consecutiveFailures, hibernateCheckinInterval)

			for consecutiveFailures >= hibernateThreshold {
				time.Sleep(hibernateCheckinInterval)

				// Checkin to stay visible to the server
				newSchedule, status, err := checkin(cfg)
				if err != nil {
					log.Printf("Hibernate checkin failed: %v", err)
					continue
				}
				if status != "approved" {
					log.Printf("Status changed to %s during hibernate — re-entering approval loop", status)
					schedule = waitForApproval(cfg)
					consecutiveFailures = 0
					break
				}
				schedule = newSchedule

				// Try a single fetch to see if we're unblocked
				body, err := fetchAVL(schedule)
				if err != nil {
					log.Printf("Hibernate probe fetch failed (%d consecutive): %v",
						consecutiveFailures, err)
					// Report the failure to the server
					body = errorBody(err)
					report(cfg, body)
					continue
				}

				// Fetch succeeded — we're back!
				log.Printf("Hibernate probe succeeded — resuming normal operation")
				consecutiveFailures = 0
				newSchedule, err = report(cfg, body)
				if err != nil {
					log.Printf("Report error after hibernate recovery: %v", err)
				} else {
					schedule = newSchedule
				}
			}
			baseInterval = time.Duration(schedule.IntervalSeconds) * time.Second
			continue
		}

		// Normal operation with backoff
		var sleepDuration time.Duration
		if consecutiveFailures == 0 {
			jitter := time.Duration(rand.Intn(3000)-1500) * time.Millisecond
			sleepDuration = baseInterval + jitter
		} else {
			sleepDuration = backoffDuration(baseInterval, consecutiveFailures)
			log.Printf("Backing off: sleeping %v (%d consecutive failures)",
				sleepDuration.Round(time.Second), consecutiveFailures)
		}
		time.Sleep(sleepDuration)

		body, err := fetchAVL(schedule)
		if err != nil {
			consecutiveFailures++
			log.Printf("Fetch error (%d consecutive): %v", consecutiveFailures, err)
			body = errorBody(err)
			report(cfg, body)
			continue
		}

		// Fetch succeeded — reset failure counter
		if consecutiveFailures > 0 {
			log.Printf("Fetch recovered after %d consecutive failures", consecutiveFailures)
		}
		consecutiveFailures = 0

		newSchedule, err := report(cfg, body)
		if err != nil {
			log.Printf("Report error: %v", err)
			continue
		}
		if newSchedule.IntervalSeconds != schedule.IntervalSeconds ||
			newSchedule.OffsetSeconds != schedule.OffsetSeconds ||
			newSchedule.FetchURL != schedule.FetchURL {
			schedule = newSchedule
			baseInterval = time.Duration(schedule.IntervalSeconds) * time.Second
			log.Printf("Schedule updated: every %ds, offset %ds", schedule.IntervalSeconds, schedule.OffsetSeconds)
		}
	}
}
