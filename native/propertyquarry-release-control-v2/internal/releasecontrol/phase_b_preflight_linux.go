//go:build linux && amd64

package releasecontrol

import (
	"bytes"
	"crypto/ed25519"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"crypto/x509"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

const (
	phaseBPreflightEvidenceSchema  = "propertyquarry.release-control.phase-b-preflight-identity-evidence.v2"
	phaseBPreflightJournalSchema   = "propertyquarry.release-control.phase-b-preflight-journal-event.v2"
	phaseBPreflightSignatureDomain = "propertyquarry.release-control.phase-b-non-authorizing-preflight-evidence.v2\x00"
	phaseBPreflightRequestDomain   = "propertyquarry.release-control.phase-b-preflight-request-binding.v2\x00"
	phaseBPreflightLockName        = ".phase-b-preflight.lock"
	phaseBPreflightMaximumEvents   = 100_000
	phaseBPreflightMaximumPending  = 1
	phaseBPreflightMaximumBytes    = 1_048_576
	phaseBPreflightMaximumJournal  = 33_554_432
	renameNoReplace                = 1
	phaseBSYSRenameat2             = 316 // Linux AMD64, the package's sole target.
)

var (
	phaseBEventNamePattern   = regexp.MustCompile(`^phase-b-preflight-([0-9]{20})\.v2\.json$`)
	phaseBPendingNamePattern = regexp.MustCompile(`^\.phase-b-preflight-pending-[0-9a-f]{64}\.tmp$`)
)

type phaseBPreflightInput struct {
	Operation           string
	RequestID           string
	Nonce               string
	ExpectedJournalHead string
	Bearer              []byte
	KeySet              *phaseBGitHubKeySet
	Policy              *phaseBRootPolicy
	EvaluatedAt         time.Time
}

type phaseBStoredEvidence struct {
	Sequence          int64
	PredecessorDigest string
	RequestID         string
	Nonce             string
	RequestDigest     string
	EvidenceDigest    string
	Canonical         []byte
	Wire              []byte
}

func (evidence *phaseBStoredEvidence) release() {
	if evidence == nil {
		return
	}
	zero(evidence.Canonical)
	zero(evidence.Wire)
	*evidence = phaseBStoredEvidence{}
}

func issuePhaseBNonAuthorizingPreflight(
	journalDirectoryFD int,
	input phaseBPreflightInput,
	signingKey ed25519.PrivateKey,
) ([]byte, error) {
	if input.Operation != "release-preflight" ||
		!requestIdentifierPattern.MatchString(input.RequestID) ||
		!requestIdentifierPattern.MatchString(input.Nonce) ||
		!requestDigestPattern.MatchString(input.ExpectedJournalHead) ||
		input.Policy == nil || input.KeySet == nil || input.EvaluatedAt.IsZero() ||
		len(signingKey) != ed25519.PrivateKeySize {
		return nil, fmt.Errorf("phase-b preflight input invalid")
	}
	if err := validatePhaseBEd25519PrivateKey(signingKey); err != nil {
		return nil, err
	}
	identity, err := verifyPhaseBGitHubOIDC(input.Bearer, input.KeySet, input.Policy, input.EvaluatedAt)
	if err != nil {
		return nil, err
	}
	if input.Nonce != identity.TokenID {
		return nil, fmt.Errorf("phase-b preflight nonce is not OIDC jti")
	}
	requestBinding, err := phaseBPreflightRequestBinding(input, identity)
	if err != nil {
		return nil, err
	}
	defer zero(requestBinding)
	requestDigest := domainSeparatedDigest([]byte(phaseBPreflightRequestDomain), requestBinding)
	validUntil := identity.ExpiresAt
	policyDeadline := input.EvaluatedAt.Unix() + input.Policy.MaxPreflightValidity
	if policyDeadline < validUntil {
		validUntil = policyDeadline
	}
	if validUntil <= input.EvaluatedAt.Unix() {
		return nil, fmt.Errorf("phase-b preflight validity exhausted")
	}
	return commitPhaseBPreflightEvidence(
		journalDirectoryFD,
		input,
		identity,
		requestDigest,
		validUntil,
		signingKey,
	)
}

func phaseBPreflightRequestBinding(
	input phaseBPreflightInput,
	identity *phaseBVerifiedGitHubIdentity,
) ([]byte, error) {
	if identity == nil || input.Policy == nil || input.KeySet == nil {
		return nil, fmt.Errorf("phase-b preflight binding unavailable")
	}
	return canonicalJSON(map[string]any{
		"schema":                 "propertyquarry.release-control.phase-b-preflight-request-binding.v2",
		"operation":              input.Operation,
		"request_id":             input.RequestID,
		"nonce":                  input.Nonce,
		"oidc_token_digest":      identity.TokenDigest,
		"oidc_key_id":            identity.KeyID,
		"oidc_jwks_digest":       identity.KeySetDigest,
		"root_policy_digest":     input.Policy.Digest,
		"decision_policy_digest": input.Policy.DecisionPolicyDigest,
		"identity":               phaseBGitHubIdentityJSON(identity),
	})
}

func phaseBGitHubIdentityJSON(identity *phaseBVerifiedGitHubIdentity) map[string]any {
	return map[string]any{
		"audience":            identity.Audience,
		"subject":             identity.Subject,
		"repository":          identity.Repository,
		"repository_id":       identity.RepositoryID,
		"repository_owner_id": identity.RepositoryOwnerID,
		"ref":                 identity.Ref,
		"candidate_sha":       identity.CandidateSHA,
		"workflow_ref":        identity.WorkflowRef,
		"workflow_sha":        identity.WorkflowSHA,
		"run_id":              identity.RunID,
		"run_attempt":         json.Number(strconv.FormatInt(identity.RunAttempt, 10)),
		"environment":         identity.Environment,
		"check_run_id":        identity.CheckRunID,
		"oidc_jti":            identity.TokenID,
		"issued_at":           json.Number(strconv.FormatInt(identity.IssuedAt, 10)),
		"not_before":          json.Number(strconv.FormatInt(identity.NotBefore, 10)),
		"expires_at":          json.Number(strconv.FormatInt(identity.ExpiresAt, 10)),
	}
}

func commitPhaseBPreflightEvidence(
	directoryFD int,
	input phaseBPreflightInput,
	identity *phaseBVerifiedGitHubIdentity,
	requestDigest string,
	validUntil int64,
	signingKey ed25519.PrivateKey,
) ([]byte, error) {
	if err := validatePhaseBJournalDirectory(directoryFD); err != nil {
		return nil, err
	}
	lockFD, err := syscall.Openat(
		directoryFD,
		phaseBPreflightLockName,
		syscall.O_CREAT|syscall.O_RDWR|syscall.O_CLOEXEC|syscall.O_NOFOLLOW,
		0o600,
	)
	if err != nil {
		return nil, fmt.Errorf("phase-b journal lock unavailable")
	}
	defer syscall.Close(lockFD)
	if err := validatePhaseBJournalFileFD(lockFD, 0, false); err != nil {
		return nil, err
	}
	var lockStat syscall.Stat_t
	if err := syscall.Fstat(lockFD, &lockStat); err != nil {
		return nil, fmt.Errorf("phase-b journal lock metadata unavailable")
	}
	lockIdentity := identityFromStat(lockStat)
	if err := syscall.Flock(lockFD, syscall.LOCK_EX); err != nil {
		return nil, fmt.Errorf("phase-b journal lock failed")
	}
	defer syscall.Flock(lockFD, syscall.LOCK_UN)
	if err := revalidatePhaseBJournalAuthority(directoryFD, lockFD, lockIdentity); err != nil {
		return nil, err
	}

	events, head, err := readPhaseBJournal(directoryFD, signingKey.Public().(ed25519.PublicKey))
	if err != nil {
		return nil, err
	}
	defer func() {
		for _, event := range events {
			event.release()
		}
	}()
	for _, event := range events {
		if event.RequestID == input.RequestID || event.Nonce == input.Nonce {
			if event.RequestID == input.RequestID && event.Nonce == input.Nonce &&
				event.RequestDigest == requestDigest {
				if err := revalidatePhaseBJournalAuthority(directoryFD, lockFD, lockIdentity); err != nil {
					return nil, err
				}
				return append([]byte(nil), event.Wire...), nil
			}
			return nil, fmt.Errorf("phase-b preflight replay conflict")
		}
	}
	if head != input.ExpectedJournalHead {
		return nil, fmt.Errorf("phase-b preflight journal CAS mismatch")
	}
	sequence := int64(len(events) + 1)
	payload, err := phaseBPreflightEvidencePayload(
		sequence,
		head,
		input,
		identity,
		requestDigest,
		validUntil,
		signingKey.Public().(ed25519.PublicKey),
	)
	if err != nil {
		return nil, err
	}
	defer zero(payload)
	wire, canonical, err := signPhaseBPreflightPayload(payload, signingKey)
	if err != nil {
		return nil, err
	}
	defer zero(canonical)
	verified, err := verifyPhaseBPreflightEvidence(wire, signingKey.Public().(ed25519.PublicKey))
	if err != nil {
		zero(wire)
		return nil, fmt.Errorf("phase-b evidence self-verification failed")
	}
	verified.release()
	if err := writePhaseBJournalEvent(directoryFD, sequence, wire); err != nil {
		zero(wire)
		return nil, err
	}
	if err := revalidatePhaseBJournalAuthority(directoryFD, lockFD, lockIdentity); err != nil {
		zero(wire)
		return nil, err
	}
	return wire, nil
}

func revalidatePhaseBJournalAuthority(
	directoryFD int,
	lockFD int,
	expectedLock stableIdentity,
) error {
	if err := validatePhaseBJournalDirectory(directoryFD); err != nil {
		return err
	}
	if err := validatePhaseBJournalFileFD(lockFD, 0, false); err != nil {
		return err
	}
	var retained syscall.Stat_t
	if err := syscall.Fstat(lockFD, &retained); err != nil || identityFromStat(retained) != expectedLock {
		return fmt.Errorf("phase-b journal retained lock changed")
	}
	reopenedFD, err := syscall.Openat(
		directoryFD,
		phaseBPreflightLockName,
		syscall.O_RDONLY|syscall.O_CLOEXEC|syscall.O_NOFOLLOW|syscall.O_NONBLOCK,
		0,
	)
	if err != nil {
		return fmt.Errorf("phase-b journal lock path unavailable")
	}
	defer syscall.Close(reopenedFD)
	if err := validatePhaseBJournalFileFD(reopenedFD, 0, false); err != nil {
		return err
	}
	var reopened syscall.Stat_t
	if err := syscall.Fstat(reopenedFD, &reopened); err != nil || identityFromStat(reopened) != expectedLock {
		return fmt.Errorf("phase-b journal lock path changed")
	}
	return nil
}

func phaseBPreflightEvidencePayload(
	sequence int64,
	predecessor string,
	input phaseBPreflightInput,
	identity *phaseBVerifiedGitHubIdentity,
	requestDigest string,
	validUntil int64,
	publicKey ed25519.PublicKey,
) ([]byte, error) {
	keyID, err := phaseBEd25519KeyID(publicKey)
	if err != nil {
		return nil, err
	}
	requiredChecks := make([]any, 0, len(input.Policy.RequiredChecks))
	for _, check := range input.Policy.RequiredChecks {
		requiredChecks = append(requiredChecks, check)
	}
	return canonicalJSON(map[string]any{
		"schema":                                 phaseBPreflightEvidenceSchema,
		"version":                                json.Number("2"),
		"journal_schema":                         phaseBPreflightJournalSchema,
		"journal_sequence":                       json.Number(strconv.FormatInt(sequence, 10)),
		"journal_predecessor_digest":             predecessor,
		"operation":                              input.Operation,
		"request_id":                             input.RequestID,
		"nonce":                                  input.Nonce,
		"request_binding_digest":                 requestDigest,
		"root_policy_digest":                     input.Policy.Digest,
		"root_policy_role_digest":                input.Policy.AuthenticatedRoleHash,
		"decision_policy_digest":                 input.Policy.DecisionPolicyDigest,
		"required_checks":                        requiredChecks,
		"github_identity":                        phaseBGitHubIdentityJSON(identity),
		"github_oidc_issuer":                     phaseBGitHubIssuer,
		"github_oidc_discovery_url":              input.KeySet.DiscoveryURL,
		"github_oidc_jwks_url":                   input.KeySet.JWKSURL,
		"github_oidc_jwks_digest":                input.KeySet.BodyDigest,
		"github_oidc_key_id":                     identity.KeyID,
		"github_oidc_signature_verified":         true,
		"github_oidc_keyset_source":              "package-internal-unactivated-input",
		"github_oidc_transport_binding_verified": false,
		"candidate_binding_verified":             true,
		"workflow_binding_verified":              true,
		"environment_binding_verified":           true,
		"root_policy_binding_verified":           true,
		"job_name_binding_verified":              false,
		"policy_job":                             input.Policy.Identity.Job,
		"evaluated_at":                           json.Number(strconv.FormatInt(input.EvaluatedAt.Unix(), 10)),
		"valid_until":                            json.Number(strconv.FormatInt(validUntil, 10)),
		"disposition":                            "identity-verified-non-authorizing",
		"authoritative":                          false,
		"ready":                                  false,
		"production_ready":                       false,
		"performs_release_effects":               false,
		"release_effects_authorized":             false,
		"evidence_key_id":                        keyID,
	})
}

func signPhaseBPreflightPayload(
	payload []byte,
	privateKey ed25519.PrivateKey,
) ([]byte, []byte, error) {
	if len(payload) < 1 || len(payload) > phaseBPreflightMaximumBytes ||
		len(privateKey) != ed25519.PrivateKeySize {
		return nil, nil, fmt.Errorf("phase-b evidence signing input invalid")
	}
	if err := validatePhaseBEd25519PrivateKey(privateKey); err != nil {
		return nil, nil, err
	}
	value, err := decodeStrictJSON(payload)
	if err != nil {
		return nil, nil, fmt.Errorf("phase-b evidence payload invalid")
	}
	canonicalPayload, err := canonicalJSON(value)
	if err != nil || !bytes.Equal(canonicalPayload, payload) {
		zero(canonicalPayload)
		return nil, nil, fmt.Errorf("phase-b evidence payload is not canonical")
	}
	defer zero(canonicalPayload)
	publicKey := privateKey.Public().(ed25519.PublicKey)
	keyID, err := phaseBEd25519KeyID(publicKey)
	if err != nil {
		return nil, nil, err
	}
	message := domainSeparatedMessage([]byte(phaseBPreflightSignatureDomain), payload)
	signature := ed25519.Sign(privateKey, message)
	if !ed25519.Verify(publicKey, message, signature) {
		zero(message)
		zero(signature)
		return nil, nil, fmt.Errorf("phase-b evidence signature self-check failed")
	}
	zero(message)
	defer zero(signature)
	wrapper, err := canonicalJSON(map[string]any{
		"payload": value,
		"signature_profile": map[string]any{
			"algorithm":      "ed25519",
			"encoding":       "base64url-no-padding",
			"key_id":         keyID,
			"signed_message": "domain-separated-uint64be-length-prefixed-canonical-json",
		},
		"signature": base64.RawURLEncoding.EncodeToString(signature),
	})
	if err != nil || len(wrapper) > phaseBPreflightMaximumBytes-1 {
		zero(wrapper)
		return nil, nil, fmt.Errorf("phase-b evidence wrapper invalid")
	}
	wire := append(append([]byte(nil), wrapper...), '\n')
	return wire, wrapper, nil
}

func validatePhaseBEd25519PrivateKey(privateKey ed25519.PrivateKey) error {
	if len(privateKey) != ed25519.PrivateKeySize {
		return fmt.Errorf("phase-b evidence private key invalid")
	}
	derived := ed25519.NewKeyFromSeed(privateKey[:ed25519.SeedSize])
	consistent := subtle.ConstantTimeCompare(derived, privateKey) == 1
	zero(derived)
	if !consistent {
		return fmt.Errorf("phase-b evidence private key inconsistent")
	}
	return nil
}

func verifyPhaseBPreflightEvidence(raw []byte, publicKey ed25519.PublicKey) (*phaseBStoredEvidence, error) {
	if len(raw) < 2 || len(raw) > phaseBPreflightMaximumBytes || raw[len(raw)-1] != '\n' ||
		bytes.Contains(raw[:len(raw)-1], []byte{'\n'}) || len(publicKey) != ed25519.PublicKeySize {
		return nil, fmt.Errorf("phase-b evidence framing invalid")
	}
	canonicalWrapper := append([]byte(nil), raw[:len(raw)-1]...)
	value, err := decodeStrictJSON(canonicalWrapper)
	if err != nil {
		zero(canonicalWrapper)
		return nil, fmt.Errorf("phase-b evidence invalid")
	}
	outer, ok := value.(map[string]any)
	if !ok || !hasExactKeys(outer, "payload", "signature_profile", "signature") {
		zero(canonicalWrapper)
		return nil, fmt.Errorf("phase-b evidence invalid")
	}
	reencoded, err := canonicalJSON(outer)
	if err != nil || !bytes.Equal(reencoded, canonicalWrapper) {
		zero(reencoded)
		zero(canonicalWrapper)
		return nil, fmt.Errorf("phase-b evidence is not canonical")
	}
	zero(reencoded)
	profile, ok := outer["signature_profile"].(map[string]any)
	keyID, keyErr := phaseBEd25519KeyID(publicKey)
	if !ok || !hasExactKeys(profile, "algorithm", "encoding", "key_id", "signed_message") ||
		!exactStringEquals(profile["algorithm"], "ed25519") ||
		!exactStringEquals(profile["encoding"], "base64url-no-padding") ||
		!exactStringEquals(profile["key_id"], keyID) ||
		!exactStringEquals(profile["signed_message"], "domain-separated-uint64be-length-prefixed-canonical-json") ||
		keyErr != nil {
		zero(canonicalWrapper)
		return nil, fmt.Errorf("phase-b evidence signature profile invalid")
	}
	signatureText, ok := exactString(outer["signature"])
	if !ok {
		zero(canonicalWrapper)
		return nil, fmt.Errorf("phase-b evidence signature invalid")
	}
	signature, err := decodePhaseBBase64URL([]byte(signatureText), ed25519.SignatureSize)
	if err != nil || len(signature) != ed25519.SignatureSize {
		zero(signature)
		zero(canonicalWrapper)
		return nil, fmt.Errorf("phase-b evidence signature invalid")
	}
	defer zero(signature)
	payloadObject, ok := outer["payload"].(map[string]any)
	if !ok {
		zero(canonicalWrapper)
		return nil, fmt.Errorf("phase-b evidence payload invalid")
	}
	payload, err := canonicalJSON(payloadObject)
	if err != nil {
		zero(canonicalWrapper)
		return nil, fmt.Errorf("phase-b evidence payload invalid")
	}
	defer zero(payload)
	message := domainSeparatedMessage([]byte(phaseBPreflightSignatureDomain), payload)
	verified := ed25519.Verify(publicKey, message, signature)
	zero(message)
	if !verified {
		zero(canonicalWrapper)
		return nil, fmt.Errorf("phase-b evidence signature invalid")
	}
	if !hasPhaseBNonAuthorizingShape(payloadObject, keyID) {
		zero(canonicalWrapper)
		return nil, fmt.Errorf("phase-b evidence authority scope invalid")
	}
	sequence, ok := exactBoundedInt(payloadObject["journal_sequence"], 1)
	if !ok || sequence > phaseBPreflightMaximumEvents {
		zero(canonicalWrapper)
		return nil, fmt.Errorf("phase-b evidence sequence invalid")
	}
	predecessor, predecessorOK := exactString(payloadObject["journal_predecessor_digest"])
	requestID, requestOK := exactString(payloadObject["request_id"])
	nonce, nonceOK := exactString(payloadObject["nonce"])
	requestDigest, digestOK := exactString(payloadObject["request_binding_digest"])
	if !predecessorOK || !requestDigestPattern.MatchString(predecessor) ||
		!requestOK || !requestIdentifierPattern.MatchString(requestID) ||
		!nonceOK || !requestIdentifierPattern.MatchString(nonce) ||
		!digestOK || !requestDigestPattern.MatchString(requestDigest) {
		zero(canonicalWrapper)
		return nil, fmt.Errorf("phase-b evidence replay binding invalid")
	}
	return &phaseBStoredEvidence{
		Sequence:          sequence,
		PredecessorDigest: predecessor,
		RequestID:         requestID,
		Nonce:             nonce,
		RequestDigest:     requestDigest,
		EvidenceDigest:    sha256Digest(canonicalWrapper),
		Canonical:         canonicalWrapper,
		Wire:              append([]byte(nil), raw...),
	}, nil
}

func hasPhaseBNonAuthorizingShape(payload map[string]any, keyID string) bool {
	version, versionOK := exactBoundedInt(payload["version"], 2)
	evaluatedAt, evaluatedAtOK := exactBoundedInt(payload["evaluated_at"], 0)
	validUntil, validUntilOK := exactBoundedInt(payload["valid_until"], 1)
	policyJob, policyJobOK := validRequestIdentifier(payload["policy_job"])
	jwksURL, jwksURLOK := exactString(payload["github_oidc_jwks_url"])
	githubKeyID, githubKeyIDOK := exactString(payload["github_oidc_key_id"])
	return hasExactKeys(
		payload,
		"schema",
		"version",
		"journal_schema",
		"journal_sequence",
		"journal_predecessor_digest",
		"operation",
		"request_id",
		"nonce",
		"request_binding_digest",
		"root_policy_digest",
		"root_policy_role_digest",
		"decision_policy_digest",
		"required_checks",
		"github_identity",
		"github_oidc_issuer",
		"github_oidc_discovery_url",
		"github_oidc_jwks_url",
		"github_oidc_jwks_digest",
		"github_oidc_key_id",
		"github_oidc_signature_verified",
		"github_oidc_keyset_source",
		"github_oidc_transport_binding_verified",
		"candidate_binding_verified",
		"workflow_binding_verified",
		"environment_binding_verified",
		"root_policy_binding_verified",
		"job_name_binding_verified",
		"policy_job",
		"evaluated_at",
		"valid_until",
		"disposition",
		"authoritative",
		"ready",
		"production_ready",
		"performs_release_effects",
		"release_effects_authorized",
		"evidence_key_id",
	) &&
		versionOK && version == 2 && evaluatedAtOK && validUntilOK && validUntil > evaluatedAt &&
		policyJobOK && policyJob != "" && validPhaseBRequiredChecks(payload["required_checks"]) &&
		validPhaseBEvidenceIdentity(payload) && jwksURLOK && validatePhaseBGitHubHTTPSURL(jwksURL) == nil &&
		githubKeyIDOK && githubKeyID != "" && len(githubKeyID) <= 256 &&
		!strings.ContainsAny(githubKeyID, "\x00\r\n") &&
		phaseBRequestDigestValue(payload["request_binding_digest"]) &&
		phaseBRequestDigestValue(payload["root_policy_digest"]) &&
		phaseBRequestDigestValue(payload["root_policy_role_digest"]) &&
		phaseBRequestDigestValue(payload["decision_policy_digest"]) &&
		phaseBRequestDigestValue(payload["github_oidc_jwks_digest"]) &&
		exactStringEquals(payload["evidence_key_id"], keyID) &&
		exactStringEquals(payload["github_oidc_issuer"], phaseBGitHubIssuer) &&
		exactStringEquals(payload["github_oidc_discovery_url"], phaseBGitHubDiscoveryURL) &&
		exactStringEquals(payload["github_oidc_keyset_source"], "package-internal-unactivated-input") &&
		exactStringEquals(payload["schema"], phaseBPreflightEvidenceSchema) &&
		exactStringEquals(payload["journal_schema"], phaseBPreflightJournalSchema) &&
		exactStringEquals(payload["operation"], "release-preflight") &&
		exactStringEquals(payload["disposition"], "identity-verified-non-authorizing") &&
		exactBoolEquals(payload["github_oidc_signature_verified"], true) &&
		exactBoolEquals(payload["github_oidc_transport_binding_verified"], false) &&
		exactBoolEquals(payload["candidate_binding_verified"], true) &&
		exactBoolEquals(payload["workflow_binding_verified"], true) &&
		exactBoolEquals(payload["environment_binding_verified"], true) &&
		exactBoolEquals(payload["root_policy_binding_verified"], true) &&
		exactBoolEquals(payload["job_name_binding_verified"], false) &&
		exactBoolEquals(payload["authoritative"], false) &&
		exactBoolEquals(payload["ready"], false) &&
		exactBoolEquals(payload["production_ready"], false) &&
		exactBoolEquals(payload["performs_release_effects"], false) &&
		exactBoolEquals(payload["release_effects_authorized"], false)
}

func phaseBRequestDigestValue(value any) bool {
	digest, ok := exactString(value)
	return ok && requestDigestPattern.MatchString(digest)
}

func validPhaseBRequiredChecks(value any) bool {
	checks, ok := value.([]any)
	if !ok || len(checks) < 1 || len(checks) > 256 {
		return false
	}
	seen := make(map[string]struct{}, len(checks))
	for _, raw := range checks {
		check, ok := validRequestIdentifier(raw)
		if !ok {
			return false
		}
		if _, duplicate := seen[check]; duplicate {
			return false
		}
		seen[check] = struct{}{}
	}
	return true
}

func validPhaseBEvidenceIdentity(payload map[string]any) bool {
	identity, ok := payload["github_identity"].(map[string]any)
	if !ok || !hasExactKeys(
		identity,
		"audience",
		"subject",
		"repository",
		"repository_id",
		"repository_owner_id",
		"ref",
		"candidate_sha",
		"workflow_ref",
		"workflow_sha",
		"run_id",
		"run_attempt",
		"environment",
		"check_run_id",
		"oidc_jti",
		"issued_at",
		"not_before",
		"expires_at",
	) {
		return false
	}
	for _, name := range []string{
		"audience", "subject", "repository", "ref", "workflow_ref", "run_id", "environment", "oidc_jti",
	} {
		value, ok := exactString(identity[name])
		if !ok || value == "" || len(value) > 2048 || strings.ContainsAny(value, "\x00\r\n") {
			return false
		}
	}
	candidateSHA, candidateOK := exactString(identity["candidate_sha"])
	workflowSHA, workflowOK := exactString(identity["workflow_sha"])
	repositoryID, repositoryIDOK := exactString(identity["repository_id"])
	repositoryOwnerID, repositoryOwnerIDOK := exactString(identity["repository_owner_id"])
	checkRunID, checkRunIDOK := exactString(identity["check_run_id"])
	runAttempt, runAttemptOK := exactBoundedInt(identity["run_attempt"], 1)
	issuedAt, issuedAtOK := exactBoundedInt(identity["issued_at"], 0)
	notBefore, notBeforeOK := exactBoundedInt(identity["not_before"], 0)
	expiresAt, expiresAtOK := exactBoundedInt(identity["expires_at"], 1)
	evaluatedAt, evaluatedAtOK := exactBoundedInt(payload["evaluated_at"], 0)
	validUntil, validUntilOK := exactBoundedInt(payload["valid_until"], 1)
	nonce, nonceOK := exactString(payload["nonce"])
	tokenID, tokenIDOK := exactString(identity["oidc_jti"])
	subject, _ := exactString(identity["subject"])
	repository, _ := exactString(identity["repository"])
	environment, _ := exactString(identity["environment"])
	skew := phaseBClockSkewSeconds()
	if !evaluatedAtOK || evaluatedAt > int64(9_223_372_036_854_775_807)-skew {
		return false
	}
	evaluatedWithSkew := evaluatedAt + skew
	return candidateOK && requestSHA1Pattern.MatchString(candidateSHA) &&
		workflowOK && requestSHA1Pattern.MatchString(workflowSHA) &&
		repositoryIDOK && decimalIdentifier(repositoryID) &&
		repositoryOwnerIDOK && decimalIdentifier(repositoryOwnerID) &&
		checkRunIDOK && decimalIdentifier(checkRunID) &&
		runAttemptOK && runAttempt >= 1 && issuedAtOK && notBeforeOK && expiresAtOK &&
		validUntilOK && expiresAt > issuedAt && notBefore >= issuedAt-skew &&
		issuedAt <= evaluatedWithSkew && notBefore <= evaluatedWithSkew &&
		evaluatedWithSkew < expiresAt &&
		validUntil > evaluatedAt && validUntil <= expiresAt &&
		validPhaseBPolicySubject(subject, repository, repositoryOwnerID, repositoryID, environment) &&
		nonceOK && tokenIDOK && nonce == tokenID
}

func phaseBEd25519KeyID(publicKey ed25519.PublicKey) (string, error) {
	if len(publicKey) != ed25519.PublicKeySize {
		return "", fmt.Errorf("phase-b evidence public key invalid")
	}
	der, err := x509.MarshalPKIXPublicKey(publicKey)
	if err != nil {
		return "", fmt.Errorf("phase-b evidence public key invalid")
	}
	digest := sha256.Sum256(der)
	zero(der)
	return "sha256:" + hex.EncodeToString(digest[:]), nil
}

func validatePhaseBJournalDirectory(fd int) error {
	if fd < 3 {
		return fmt.Errorf("phase-b journal descriptor invalid")
	}
	var stat syscall.Stat_t
	if err := syscall.Fstat(fd, &stat); err != nil || stat.Mode&syscall.S_IFMT != syscall.S_IFDIR ||
		stat.Mode&0o7777 != 0o700 || stat.Uid != uint32(os.Geteuid()) || stat.Gid != uint32(os.Getegid()) {
		return fmt.Errorf("phase-b journal directory invalid")
	}
	return setCloseOnExec(fd)
}

func validatePhaseBJournalFileFD(fd int, maximum int64, requireContent bool) error {
	var stat syscall.Stat_t
	if err := syscall.Fstat(fd, &stat); err != nil || stat.Mode&syscall.S_IFMT != syscall.S_IFREG ||
		stat.Nlink != 1 || stat.Mode&0o7777 != 0o600 ||
		stat.Uid != uint32(os.Geteuid()) || stat.Gid != uint32(os.Getegid()) ||
		stat.Size < 0 || stat.Size > maximum || (requireContent && stat.Size < 1) {
		return fmt.Errorf("phase-b journal file invalid")
	}
	return setCloseOnExec(fd)
}

func readPhaseBJournal(
	directoryFD int,
	publicKey ed25519.PublicKey,
) ([]*phaseBStoredEvidence, string, error) {
	// F_DUPFD_CLOEXEC shares a directory file description and therefore its
	// read offset. Reset the already-validated private directory descriptor
	// under the journal lock before every complete snapshot.
	if offset, err := syscall.Seek(directoryFD, 0, io.SeekStart); err != nil || offset != 0 {
		return nil, "", fmt.Errorf("phase-b journal directory rewind failed")
	}
	names, err := phaseBBoundedDirectoryNames(
		directoryFD,
		phaseBPreflightMaximumEvents+phaseBPreflightMaximumPending+1,
	)
	if err != nil {
		return nil, "", fmt.Errorf("phase-b journal listing failed")
	}
	eventNames := make([]string, 0, len(names))
	pendingNames := make([]string, 0, phaseBPreflightMaximumPending)
	pendingCount := 0
	for _, name := range names {
		switch {
		case name == phaseBPreflightLockName:
			continue
		case phaseBPendingNamePattern.MatchString(name):
			pendingCount++
			if pendingCount > phaseBPreflightMaximumPending {
				return nil, "", fmt.Errorf("phase-b pending journal file limit exceeded")
			}
			fd, openErr := syscall.Openat(directoryFD, name, syscall.O_RDONLY|syscall.O_CLOEXEC|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0)
			if openErr != nil || validatePhaseBJournalFileFD(fd, phaseBPreflightMaximumBytes, false) != nil {
				if fd >= 0 {
					_ = syscall.Close(fd)
				}
				return nil, "", fmt.Errorf("phase-b pending journal file invalid")
			}
			_ = syscall.Close(fd)
			pendingNames = append(pendingNames, name)
			continue
		case phaseBEventNamePattern.MatchString(name):
			eventNames = append(eventNames, name)
		default:
			return nil, "", fmt.Errorf("phase-b journal contains an unknown entry")
		}
	}
	if len(eventNames) > phaseBPreflightMaximumEvents {
		return nil, "", fmt.Errorf("phase-b journal event limit exceeded")
	}
	sort.Strings(eventNames)
	events := make([]*phaseBStoredEvidence, 0, len(eventNames))
	head := phaseBPreflightGenesisDigest()
	seenRequests := make(map[string]struct{}, len(eventNames)+len(pendingNames))
	seenNonces := make(map[string]struct{}, len(eventNames)+len(pendingNames))
	totalBytes := int64(0)
	for index, name := range eventNames {
		expectedName := phaseBPreflightEventName(int64(index + 1))
		if name != expectedName {
			for _, event := range events {
				event.release()
			}
			return nil, "", fmt.Errorf("phase-b journal sequence gap")
		}
		raw, readErr := readPhaseBJournalFile(directoryFD, name, true)
		if readErr != nil {
			for _, event := range events {
				event.release()
			}
			return nil, "", readErr
		}
		if int64(len(raw)) > phaseBPreflightMaximumJournal-totalBytes {
			zero(raw)
			for _, event := range events {
				event.release()
			}
			return nil, "", fmt.Errorf("phase-b journal byte limit exceeded")
		}
		totalBytes += int64(len(raw))
		event, verifyErr := verifyPhaseBPreflightEvidence(raw, publicKey)
		zero(raw)
		if verifyErr != nil || event.Sequence != int64(index+1) || event.PredecessorDigest != head {
			if event != nil {
				event.release()
			}
			for _, prior := range events {
				prior.release()
			}
			return nil, "", fmt.Errorf("phase-b journal chain invalid")
		}
		if _, duplicate := seenRequests[event.RequestID]; duplicate {
			event.release()
			for _, prior := range events {
				prior.release()
			}
			return nil, "", fmt.Errorf("phase-b journal request replay duplicate")
		}
		if _, duplicate := seenNonces[event.Nonce]; duplicate {
			event.release()
			for _, prior := range events {
				prior.release()
			}
			return nil, "", fmt.Errorf("phase-b journal nonce replay duplicate")
		}
		seenRequests[event.RequestID] = struct{}{}
		seenNonces[event.Nonce] = struct{}{}
		head = event.EvidenceDigest
		events = append(events, event)
	}
	if len(pendingNames) == 1 {
		pendingName := pendingNames[0]
		raw, readErr := readPhaseBJournalFile(directoryFD, pendingName, false)
		if readErr != nil {
			for _, event := range events {
				event.release()
			}
			return nil, "", readErr
		}
		if int64(len(raw)) > phaseBPreflightMaximumJournal-totalBytes {
			zero(raw)
			for _, event := range events {
				event.release()
			}
			return nil, "", fmt.Errorf("phase-b journal byte limit exceeded")
		}
		pending, verifyErr := verifyPhaseBPreflightEvidence(raw, publicKey)
		zero(raw)
		if verifyErr != nil {
			if err := removePhaseBAbandonedPending(directoryFD, pendingName); err != nil {
				for _, event := range events {
					event.release()
				}
				return nil, "", err
			}
			return events, head, nil
		}
		if pending.Sequence != int64(len(events)+1) || pending.PredecessorDigest != head {
			pending.release()
			for _, event := range events {
				event.release()
			}
			return nil, "", fmt.Errorf("phase-b pending journal chain invalid")
		}
		if _, duplicate := seenRequests[pending.RequestID]; duplicate {
			pending.release()
			for _, event := range events {
				event.release()
			}
			return nil, "", fmt.Errorf("phase-b pending journal request replay duplicate")
		}
		if _, duplicate := seenNonces[pending.Nonce]; duplicate {
			pending.release()
			for _, event := range events {
				event.release()
			}
			return nil, "", fmt.Errorf("phase-b pending journal nonce replay duplicate")
		}
		if err := renamePhaseBNoReplace(
			directoryFD,
			pendingName,
			phaseBPreflightEventName(pending.Sequence),
		); err != nil {
			pending.release()
			for _, event := range events {
				event.release()
			}
			return nil, "", fmt.Errorf("phase-b pending journal recovery publish failed: %w", err)
		}
		if err := syscall.Fsync(directoryFD); err != nil {
			pending.release()
			for _, event := range events {
				event.release()
			}
			return nil, "", fmt.Errorf("phase-b pending journal recovery fsync failed")
		}
		head = pending.EvidenceDigest
		events = append(events, pending)
	}
	return events, head, nil
}

func phaseBBoundedDirectoryNames(directoryFD int, maximum int) ([]string, error) {
	if maximum < 1 {
		return nil, fmt.Errorf("phase-b journal directory limit invalid")
	}
	duplicate, err := fcntl(directoryFD, syscall.F_DUPFD_CLOEXEC, 3)
	if err != nil {
		return nil, fmt.Errorf("phase-b journal directory duplication failed")
	}
	file := os.NewFile(uintptr(duplicate), "phase-b-journal-directory")
	if file == nil {
		_ = syscall.Close(duplicate)
		return nil, fmt.Errorf("phase-b journal directory wrapper failed")
	}
	names := make([]string, 0, min(maximum, 256))
	for {
		entries, readErr := file.ReadDir(128)
		for _, entry := range entries {
			if len(names) >= maximum {
				_ = file.Close()
				return nil, fmt.Errorf("phase-b journal directory entry limit exceeded")
			}
			name := entry.Name()
			if name == "" || name == "." || name == ".." ||
				strings.ContainsRune(name, '/') || strings.ContainsRune(name, 0) {
				_ = file.Close()
				return nil, fmt.Errorf("phase-b journal directory name invalid")
			}
			names = append(names, name)
		}
		if readErr == io.EOF {
			break
		}
		if readErr != nil || len(entries) == 0 {
			_ = file.Close()
			return nil, fmt.Errorf("phase-b journal directory read failed")
		}
	}
	if err := file.Close(); err != nil {
		return nil, fmt.Errorf("phase-b journal directory close failed")
	}
	sort.Strings(names)
	return names, nil
}

func removePhaseBAbandonedPending(directoryFD int, name string) error {
	if !phaseBPendingNamePattern.MatchString(name) {
		return fmt.Errorf("phase-b abandoned pending name invalid")
	}
	if err := syscall.Unlinkat(directoryFD, name); err != nil {
		return fmt.Errorf("phase-b abandoned pending removal failed")
	}
	if err := syscall.Fsync(directoryFD); err != nil {
		return fmt.Errorf("phase-b abandoned pending removal fsync failed")
	}
	return nil
}

func readPhaseBJournalFile(directoryFD int, name string, requireContent bool) ([]byte, error) {
	fd, err := syscall.Openat(directoryFD, name, syscall.O_RDONLY|syscall.O_CLOEXEC|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0)
	if err != nil {
		return nil, fmt.Errorf("phase-b journal event unavailable")
	}
	if err := validatePhaseBJournalFileFD(fd, phaseBPreflightMaximumBytes, requireContent); err != nil {
		_ = syscall.Close(fd)
		return nil, err
	}
	var before syscall.Stat_t
	if err := syscall.Fstat(fd, &before); err != nil {
		_ = syscall.Close(fd)
		return nil, fmt.Errorf("phase-b journal event metadata unavailable")
	}
	file := os.NewFile(uintptr(fd), "phase-b-journal-event")
	if file == nil {
		_ = syscall.Close(fd)
		return nil, fmt.Errorf("phase-b journal event wrapper failed")
	}
	raw, readErr := io.ReadAll(io.LimitReader(file, phaseBPreflightMaximumBytes+1))
	var after syscall.Stat_t
	statErr := syscall.Fstat(fd, &after)
	closeErr := file.Close()
	if readErr != nil || statErr != nil || closeErr != nil || identityFromStat(before) != identityFromStat(after) ||
		int64(len(raw)) != before.Size || len(raw) > phaseBPreflightMaximumBytes {
		zero(raw)
		return nil, fmt.Errorf("phase-b journal event changed during read")
	}
	reopenedFD, err := syscall.Openat(
		directoryFD,
		name,
		syscall.O_RDONLY|syscall.O_CLOEXEC|syscall.O_NOFOLLOW|syscall.O_NONBLOCK,
		0,
	)
	if err != nil {
		zero(raw)
		return nil, fmt.Errorf("phase-b journal event path unavailable after read")
	}
	if err := validatePhaseBJournalFileFD(reopenedFD, phaseBPreflightMaximumBytes, requireContent); err != nil {
		_ = syscall.Close(reopenedFD)
		zero(raw)
		return nil, err
	}
	var reopened syscall.Stat_t
	reopenStatErr := syscall.Fstat(reopenedFD, &reopened)
	reopenCloseErr := syscall.Close(reopenedFD)
	if reopenStatErr != nil || reopenCloseErr != nil || identityFromStat(reopened) != identityFromStat(before) {
		zero(raw)
		return nil, fmt.Errorf("phase-b journal event path changed during read")
	}
	return raw, nil
}

func writePhaseBJournalEvent(directoryFD int, sequence int64, wire []byte) error {
	if sequence < 1 || sequence > phaseBPreflightMaximumEvents || len(wire) < 2 ||
		len(wire) > phaseBPreflightMaximumBytes {
		return fmt.Errorf("phase-b journal event write invalid")
	}
	random := make([]byte, 32)
	if _, err := io.ReadFull(rand.Reader, random); err != nil {
		zero(random)
		return fmt.Errorf("phase-b journal pending name unavailable")
	}
	pendingName := ".phase-b-preflight-pending-" + hex.EncodeToString(random) + ".tmp"
	zero(random)
	fd, err := syscall.Openat(
		directoryFD,
		pendingName,
		syscall.O_WRONLY|syscall.O_CREAT|syscall.O_EXCL|syscall.O_CLOEXEC|syscall.O_NOFOLLOW,
		0o600,
	)
	if err != nil {
		return fmt.Errorf("phase-b journal pending event create failed")
	}
	pendingOwned := true
	defer func() {
		_ = syscall.Close(fd)
		if pendingOwned {
			_ = syscall.Unlinkat(directoryFD, pendingName)
		}
	}()
	for offset := 0; offset < len(wire); {
		count, writeErr := syscall.Write(fd, wire[offset:])
		if writeErr == syscall.EINTR {
			continue
		}
		if writeErr != nil || count < 1 {
			return fmt.Errorf("phase-b journal event write failed")
		}
		offset += count
	}
	if err := syscall.Fsync(fd); err != nil || validatePhaseBJournalFileFD(fd, phaseBPreflightMaximumBytes, true) != nil {
		return fmt.Errorf("phase-b journal event durability failed")
	}
	if err := syscall.Close(fd); err != nil {
		fd = -1
		return fmt.Errorf("phase-b journal event close failed")
	}
	fd = -1
	persisted, readErr := readPhaseBJournalFile(directoryFD, pendingName, true)
	if readErr != nil || !bytes.Equal(persisted, wire) {
		zero(persisted)
		return fmt.Errorf("phase-b journal pending event verification failed")
	}
	zero(persisted)
	finalName := phaseBPreflightEventName(sequence)
	if err := renamePhaseBNoReplace(directoryFD, pendingName, finalName); err != nil {
		return fmt.Errorf("phase-b journal event publish failed: %w", err)
	}
	pendingOwned = false
	if err := syscall.Fsync(directoryFD); err != nil {
		return fmt.Errorf("phase-b journal directory fsync failed")
	}
	return nil
}

func renamePhaseBNoReplace(directoryFD int, oldName, newName string) error {
	oldPointer, err := syscall.BytePtrFromString(oldName)
	if err != nil {
		return err
	}
	newPointer, err := syscall.BytePtrFromString(newName)
	if err != nil {
		return err
	}
	_, _, errno := syscall.Syscall6(
		phaseBSYSRenameat2,
		uintptr(directoryFD),
		uintptr(unsafe.Pointer(oldPointer)),
		uintptr(directoryFD),
		uintptr(unsafe.Pointer(newPointer)),
		renameNoReplace,
		0,
	)
	if errno != 0 {
		return errno
	}
	return nil
}

func phaseBPreflightEventName(sequence int64) string {
	return fmt.Sprintf("phase-b-preflight-%020d.v2.json", sequence)
}

func phaseBPreflightGenesisDigest() string {
	return sha256Digest([]byte("propertyquarry.release-control.phase-b-preflight-journal-genesis.v2\x00"))
}
