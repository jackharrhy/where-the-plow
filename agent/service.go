package main

import (
	"context"
	"log"
	"math/rand"
	"os"
	"time"

	"github.com/kardianos/service"
)

const serviceName = "plow-agent"
const serviceDisplayName = "Plow Agent"
const serviceDescription = "Collects snowplow GPS data for plow.jackharrhy.dev"

// plowService implements service.Interface. It manages the agent's fetch loop
// lifecycle so it can run as a system service or interactively.
type plowService struct {
	server string
	ctx    context.Context
	cancel context.CancelFunc
	done   chan struct{}
	logger service.Logger
}

func (p *plowService) Start(s service.Service) error {
	p.ctx, p.cancel = context.WithCancel(context.Background())
	p.done = make(chan struct{})
	go p.run()
	return nil
}

func (p *plowService) Stop(s service.Service) error {
	p.cancel()
	<-p.done
	return nil
}

// run is the main agent loop — registration, approval wait, and fetch/report.
func (p *plowService) run() {
	defer close(p.done)

	cfg := loadOrCreateConfig(p.server)

	if !cfg.registered {
		register(cfg)
	}

	schedule := p.waitForApproval(cfg)
	if schedule == nil {
		return // context cancelled
	}

	p.logInfo("Approved! Fetching every %ds (offset %ds)", schedule.IntervalSeconds, schedule.OffsetSeconds)

	if !p.sleep(time.Duration(schedule.OffsetSeconds) * time.Second) {
		return
	}

	consecutiveFailures := 0
	baseInterval := time.Duration(schedule.IntervalSeconds) * time.Second

	for {
		if p.ctx.Err() != nil {
			return
		}

		// Hibernate mode
		if consecutiveFailures >= hibernateThreshold {
			p.logInfo("Hibernating after %d consecutive failures — checking in every %v",
				consecutiveFailures, hibernateCheckinInterval)

			schedule = p.hibernateLoop(cfg, schedule, &consecutiveFailures)
			if schedule == nil {
				return
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
			p.logInfo("Backing off: sleeping %v (%d consecutive failures)",
				sleepDuration.Round(time.Second), consecutiveFailures)
		}
		if !p.sleep(sleepDuration) {
			return
		}

		body, err := fetchAVL(*schedule)
		if err != nil {
			consecutiveFailures++
			p.logInfo("Fetch error (%d consecutive): %v", consecutiveFailures, err)
			body = errorBody(err)
			report(cfg, body)
			continue
		}

		if consecutiveFailures > 0 {
			p.logInfo("Fetch recovered after %d consecutive failures", consecutiveFailures)
		}
		consecutiveFailures = 0

		newSchedule, err := report(cfg, body)
		if err != nil {
			p.logInfo("Report error: %v", err)
			continue
		}
		if newSchedule.IntervalSeconds != schedule.IntervalSeconds ||
			newSchedule.OffsetSeconds != schedule.OffsetSeconds ||
			newSchedule.FetchURL != schedule.FetchURL {
			*schedule = newSchedule
			baseInterval = time.Duration(schedule.IntervalSeconds) * time.Second
			p.logInfo("Schedule updated: every %ds, offset %ds", schedule.IntervalSeconds, schedule.OffsetSeconds)
		}
	}
}

// waitForApproval blocks until the agent is approved or context is cancelled.
// Returns nil if cancelled.
func (p *plowService) waitForApproval(cfg *Config) *Schedule {
	for {
		schedule, status, err := checkin(cfg)
		if err != nil {
			p.logInfo("Checkin failed: %v, retrying in 30s", err)
			if !p.sleep(30 * time.Second) {
				return nil
			}
			continue
		}
		if status == "approved" {
			return &schedule
		}
		p.logInfo("Status: %s — waiting for approval (checking every 30s)", status)
		if !p.sleep(30 * time.Second) {
			return nil
		}
	}
}

// hibernateLoop runs the hibernate checkin/probe cycle. Returns the current
// schedule, or nil if context was cancelled.
func (p *plowService) hibernateLoop(cfg *Config, schedule *Schedule, consecutiveFailures *int) *Schedule {
	for *consecutiveFailures >= hibernateThreshold {
		if !p.sleep(hibernateCheckinInterval) {
			return nil
		}

		newSchedule, status, err := checkin(cfg)
		if err != nil {
			p.logInfo("Hibernate checkin failed: %v", err)
			continue
		}
		if status != "approved" {
			p.logInfo("Status changed to %s during hibernate — re-entering approval loop", status)
			s := p.waitForApproval(cfg)
			if s == nil {
				return nil
			}
			*consecutiveFailures = 0
			return s
		}
		*schedule = newSchedule

		body, err := fetchAVL(*schedule)
		if err != nil {
			p.logInfo("Hibernate probe fetch failed (%d consecutive): %v",
				*consecutiveFailures, err)
			body = errorBody(err)
			report(cfg, body)
			continue
		}

		p.logInfo("Hibernate probe succeeded — resuming normal operation")
		*consecutiveFailures = 0
		newSched, err := report(cfg, body)
		if err != nil {
			p.logInfo("Report error after hibernate recovery: %v", err)
		} else {
			*schedule = newSched
		}
	}
	return schedule
}

// sleep waits for the given duration or until context is cancelled.
// Returns true if the sleep completed, false if cancelled.
func (p *plowService) sleep(d time.Duration) bool {
	select {
	case <-time.After(d):
		return true
	case <-p.ctx.Done():
		return false
	}
}

// logInfo logs via the service logger if available, otherwise stdlib log.
func (p *plowService) logInfo(format string, a ...interface{}) {
	if p.logger != nil {
		p.logger.Infof(format, a...)
	} else {
		log.Printf(format, a...)
	}
}

// serviceConfig builds the kardianos/service Config. When installing as a
// service, the binary is re-invoked with --run --server <url>, so the fetch
// loop starts automatically under the service manager.
//
// The config directory is baked in as PLOW_DATA_DIR so the daemon (which may
// run as root) can find the credentials that were generated by the installing
// user.
func serviceConfig(serverURL string) *service.Config {
	cfg := &service.Config{
		Name:        serviceName,
		DisplayName: serviceDisplayName,
		Description: serviceDescription,
		Arguments:   []string{"--run", "--server", serverURL},
		Option: service.KeyValue{
			"KeepAlive": true,
			"RunAtLoad": true,
		},
	}

	// Pass the config directory to the daemon so it finds the right credentials.
	// Only set if not already overridden via PLOW_DATA_DIR.
	if os.Getenv("PLOW_DATA_DIR") == "" {
		cfg.EnvVars = map[string]string{
			"PLOW_DATA_DIR": getConfigDir(),
		}
	}

	return cfg
}
