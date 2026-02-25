package main

import (
	"flag"
	"fmt"
	"log"
	"math/rand"
	"os"
	"time"
)

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
	server := flag.String("server", os.Getenv("PLOW_SERVER"), "Plow server URL")
	flag.Parse()
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

	for {
		jitter := time.Duration(rand.Intn(3000)-1500) * time.Millisecond
		time.Sleep(time.Duration(schedule.IntervalSeconds)*time.Second + jitter)

		body, err := fetchAVL(schedule)
		if err != nil {
			log.Printf("Fetch error: %v", err)
			body = []byte(fmt.Sprintf(`{"error": "%s"}`, err.Error()))
		}

		newSchedule, err := report(cfg, body)
		if err != nil {
			log.Printf("Report error: %v", err)
			continue
		}
		if newSchedule.IntervalSeconds != schedule.IntervalSeconds ||
			newSchedule.OffsetSeconds != schedule.OffsetSeconds ||
			newSchedule.FetchURL != schedule.FetchURL {
			schedule = newSchedule
			log.Printf("Schedule updated: every %ds, offset %ds", schedule.IntervalSeconds, schedule.OffsetSeconds)
		}
	}
}
