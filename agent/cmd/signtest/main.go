// Command signtest generates an ECDSA P-256 keypair, signs a fixed payload,
// and prints the results as JSON. Used by tests/test_crypto_compat.py to
// verify cross-language signature compatibility.
package main

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"log"
	"os"
)

func main() {
	// Generate keypair.
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		log.Fatal(err)
	}

	// Encode public key as PEM (PKIX / SubjectPublicKeyInfo).
	pubDER, err := x509.MarshalPKIXPublicKey(&key.PublicKey)
	if err != nil {
		log.Fatal(err)
	}
	pubPEM := pem.EncodeToMemory(&pem.Block{Type: "PUBLIC KEY", Bytes: pubDER})

	// Derive agent ID: first 16 hex chars of SHA-256(DER public key).
	h := sha256.Sum256(pubDER)
	agentID := fmt.Sprintf("%x", h[:])[:16]

	// Sign a fixed body + timestamp.
	body := []byte(`{"features": []}`)
	ts := "1700000000"

	msg := make([]byte, len(body)+len(ts))
	copy(msg, body)
	copy(msg[len(body):], ts)
	digest := sha256.Sum256(msg)

	sig, err := ecdsa.SignASN1(rand.Reader, key, digest[:])
	if err != nil {
		log.Fatal(err)
	}

	out := map[string]string{
		"public_key": string(pubPEM),
		"agent_id":   agentID,
		"body":       string(body),
		"timestamp":  ts,
		"signature":  base64.StdEncoding.EncodeToString(sig),
	}

	json.NewEncoder(os.Stdout).Encode(out)
}
