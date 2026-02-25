package main

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/pem"
	"fmt"
	"strconv"
	"time"
)

// generateKeypair creates a new ECDSA P-256 keypair.
func generateKeypair() (*ecdsa.PrivateKey, error) {
	return ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
}

// encodePrivateKeyPEM encodes a private key to PEM (EC PRIVATE KEY / SEC 1 format).
func encodePrivateKeyPEM(key *ecdsa.PrivateKey) ([]byte, error) {
	der, err := x509.MarshalECPrivateKey(key)
	if err != nil {
		return nil, fmt.Errorf("marshal EC private key: %w", err)
	}
	return pem.EncodeToMemory(&pem.Block{
		Type:  "EC PRIVATE KEY",
		Bytes: der,
	}), nil
}

// decodePrivateKeyPEM decodes a PEM-encoded EC private key.
func decodePrivateKeyPEM(data []byte) (*ecdsa.PrivateKey, error) {
	block, _ := pem.Decode(data)
	if block == nil {
		return nil, fmt.Errorf("no PEM block found")
	}
	return x509.ParseECPrivateKey(block.Bytes)
}

// encodePublicKeyPEM encodes a public key to PEM (PKIX / SubjectPublicKeyInfo format).
func encodePublicKeyPEM(key *ecdsa.PublicKey) ([]byte, error) {
	der, err := x509.MarshalPKIXPublicKey(key)
	if err != nil {
		return nil, fmt.Errorf("marshal public key: %w", err)
	}
	return pem.EncodeToMemory(&pem.Block{
		Type:  "PUBLIC KEY",
		Bytes: der,
	}), nil
}

// agentIDFromPublicKey derives a 16-char hex agent ID from SHA-256 of the
// DER-encoded public key (PKIX format).
func agentIDFromPublicKey(key *ecdsa.PublicKey) (string, error) {
	der, err := x509.MarshalPKIXPublicKey(key)
	if err != nil {
		return "", fmt.Errorf("marshal public key: %w", err)
	}
	h := sha256.Sum256(der)
	return fmt.Sprintf("%x", h[:])[:16], nil
}

// signPayload signs SHA-256(body || timestamp_bytes) with ECDSA P-256.
// Returns base64-encoded ASN.1 DER signature.
func signPayload(key *ecdsa.PrivateKey, body []byte, timestamp string) (string, error) {
	msg := make([]byte, len(body)+len(timestamp))
	copy(msg, body)
	copy(msg[len(body):], timestamp)
	h := sha256.Sum256(msg)
	sig, err := ecdsa.SignASN1(rand.Reader, key, h[:])
	if err != nil {
		return "", fmt.Errorf("sign: %w", err)
	}
	return base64.StdEncoding.EncodeToString(sig), nil
}

// currentTimestamp returns the current Unix timestamp as a string.
func currentTimestamp() string {
	return strconv.FormatInt(time.Now().Unix(), 10)
}
