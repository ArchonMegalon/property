//go:build linux

package releasecontrol

import (
	"bytes"
	"context"
	"crypto"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/tls"
	"encoding/base64"
	"fmt"
	"io"
	"math/big"
	"net"
	"net/http"
	"net/netip"
	"net/url"
	"sort"
	"strconv"
	"strings"
	"time"
)

const (
	phaseBGitHubIssuer       = "https://token.actions.githubusercontent.com"
	phaseBGitHubDiscoveryURL = "https://token.actions.githubusercontent.com/.well-known/openid-configuration"
	phaseBMaximumJWKSBytes   = 262_144
	phaseBMaximumPolicyBytes = 65_536
	phaseBMaximumOIDCBytes   = MaxBearerBytes
	phaseBClockSkew          = 30 * time.Second
	phaseBHTTPTimeout        = 10 * time.Second
)

type phaseBGitHubKeySet struct {
	Issuer       string
	DiscoveryURL string
	JWKSURL      string
	CanonicalURL string
	Body         []byte
	BodyDigest   string
}

func (keySet *phaseBGitHubKeySet) release() {
	if keySet == nil {
		return
	}
	zero(keySet.Body)
	*keySet = phaseBGitHubKeySet{}
}

type phaseBVerifiedGitHubIdentity struct {
	Audience          string
	Subject           string
	Repository        string
	RepositoryID      string
	RepositoryOwnerID string
	Ref               string
	CandidateSHA      string
	WorkflowRef       string
	WorkflowSHA       string
	RunID             string
	RunAttempt        int64
	Environment       string
	CheckRunID        string
	TokenID           string
	IssuedAt          int64
	NotBefore         int64
	ExpiresAt         int64
	KeyID             string
	TokenDigest       string
	KeySetDigest      string
}

type phaseBRootPolicy struct {
	Canonical              []byte
	Digest                 string
	Identity               quarantinedIdentity
	RepositoryID           string
	RepositoryOwnerID      string
	CheckRunID             string
	Subject                string
	RequiredChecks         []string
	DecisionPolicyDigest   string
	MaxRequestTTL          int64
	MaxPreflightValidity   int64
	AuthenticatedRoleHash  string
	AuthenticatedRoleBytes int64
}

func (policy *phaseBRootPolicy) release() {
	if policy == nil {
		return
	}
	zero(policy.Canonical)
	*policy = phaseBRootPolicy{}
}

func parseAuthenticatedPhaseBRootPolicy(raw []byte, role installedRole) (*phaseBRootPolicy, error) {
	if role.Contract.Role != "root-policy" ||
		role.Contract.Path != "/etc/propertyquarry-release-control/policy-v2.json" ||
		role.Contract.Mode != 0o640 || !role.Contract.Private ||
		role.Digest == "" || role.Size < 1 || role.Size > phaseBMaximumPolicyBytes ||
		int64(len(raw)) != role.Size ||
		sha256Digest(raw) != role.Digest {
		return nil, fmt.Errorf("phase-b root policy is not package-authenticated")
	}
	value, err := decodeStrictJSON(raw)
	if err != nil {
		return nil, fmt.Errorf("phase-b root policy invalid")
	}
	outer, ok := value.(map[string]any)
	if !ok || !hasExactKeys(
		outer,
		"schema",
		"identity",
		"required_checks",
		"max_request_ttl",
		"max_preflight_validity",
		"decision_policy_digest",
	) || !exactStringEquals(outer["schema"], "propertyquarry.release-root-policy.v2") {
		return nil, fmt.Errorf("phase-b root policy shape invalid")
	}
	identityObject, ok := outer["identity"].(map[string]any)
	if !ok || !hasExactKeys(
		identityObject,
		"audience",
		"repository",
		"ref",
		"candidate_sha",
		"workflow_ref",
		"workflow_sha",
		"run_id",
		"run_attempt",
		"job",
		"environment",
		"repository_id",
		"repository_owner_id",
		"check_run_id",
		"subject",
	) {
		return nil, fmt.Errorf("phase-b root policy identity invalid")
	}
	identity, ok := parseQuarantinedIdentity(identityObject)
	if !ok {
		return nil, fmt.Errorf("phase-b root policy identity invalid")
	}
	repositoryID, repositoryIDOK := exactString(identityObject["repository_id"])
	repositoryOwnerID, repositoryOwnerIDOK := exactString(identityObject["repository_owner_id"])
	checkRunID, checkRunIDOK := exactString(identityObject["check_run_id"])
	if !repositoryIDOK || !decimalIdentifier(repositoryID) ||
		!repositoryOwnerIDOK || !decimalIdentifier(repositoryOwnerID) ||
		!checkRunIDOK || !decimalIdentifier(checkRunID) {
		return nil, fmt.Errorf("phase-b root policy repository identity invalid")
	}
	subject, subjectOK := exactString(identityObject["subject"])
	if !subjectOK || !validPhaseBPolicySubject(
		subject,
		identity.Repository,
		repositoryOwnerID,
		repositoryID,
		identity.Environment,
	) {
		return nil, fmt.Errorf("phase-b root policy subject invalid")
	}
	checksValue, ok := outer["required_checks"].([]any)
	if !ok || len(checksValue) < 1 || len(checksValue) > 256 {
		return nil, fmt.Errorf("phase-b root policy checks invalid")
	}
	checks := make([]string, 0, len(checksValue))
	seen := make(map[string]struct{}, len(checksValue))
	for _, item := range checksValue {
		check, ok := validRequestIdentifier(item)
		if !ok {
			return nil, fmt.Errorf("phase-b root policy check invalid")
		}
		if _, duplicate := seen[check]; duplicate {
			return nil, fmt.Errorf("phase-b root policy checks duplicate")
		}
		seen[check] = struct{}{}
		checks = append(checks, check)
	}
	decisionPolicyDigest, ok := exactString(outer["decision_policy_digest"])
	if !ok || !requestDigestPattern.MatchString(decisionPolicyDigest) {
		return nil, fmt.Errorf("phase-b decision policy digest invalid")
	}
	maxRequestTTL, ok := exactBoundedInt(outer["max_request_ttl"], 1)
	if !ok || maxRequestTTL > 3600 {
		return nil, fmt.Errorf("phase-b request TTL invalid")
	}
	maxPreflightValidity, ok := exactBoundedInt(outer["max_preflight_validity"], 1)
	if !ok || maxPreflightValidity > maxRequestTTL {
		return nil, fmt.Errorf("phase-b preflight validity invalid")
	}
	canonical, err := canonicalJSON(outer)
	if err != nil || !bytes.Equal(canonical, raw) {
		zero(canonical)
		return nil, fmt.Errorf("phase-b root policy is not canonical")
	}
	return &phaseBRootPolicy{
		Canonical:              canonical,
		Digest:                 domainSeparatedDigest([]byte("propertyquarry.release-root-policy-digest.v2\x00"), canonical),
		Identity:               identity,
		RepositoryID:           repositoryID,
		RepositoryOwnerID:      repositoryOwnerID,
		CheckRunID:             checkRunID,
		Subject:                subject,
		RequiredChecks:         checks,
		DecisionPolicyDigest:   decisionPolicyDigest,
		MaxRequestTTL:          maxRequestTTL,
		MaxPreflightValidity:   maxPreflightValidity,
		AuthenticatedRoleHash:  role.Digest,
		AuthenticatedRoleBytes: role.Size,
	}, nil
}

func fetchPhaseBGitHubKeySet(ctx context.Context) (*phaseBGitHubKeySet, error) {
	if ctx == nil {
		return nil, fmt.Errorf("phase-b OIDC context missing")
	}
	discovery, _, err := fetchPhaseBHTTPSJSON(ctx, phaseBGitHubDiscoveryURL, phaseBMaximumJWKSBytes)
	if err != nil {
		return nil, err
	}
	defer zero(discovery)
	value, err := decodeStrictJSON(discovery)
	if err != nil {
		return nil, fmt.Errorf("phase-b OIDC discovery invalid")
	}
	object, ok := value.(map[string]any)
	if !ok {
		return nil, fmt.Errorf("phase-b OIDC discovery invalid")
	}
	issuer, ok := exactString(object["issuer"])
	if !ok || issuer != phaseBGitHubIssuer {
		return nil, fmt.Errorf("phase-b OIDC issuer invalid")
	}
	jwksURL, ok := exactString(object["jwks_uri"])
	if !ok || validatePhaseBGitHubHTTPSURL(jwksURL) != nil {
		return nil, fmt.Errorf("phase-b OIDC JWKS URL invalid")
	}
	body, canonicalURL, err := fetchPhaseBHTTPSJSON(ctx, jwksURL, phaseBMaximumJWKSBytes)
	if err != nil {
		return nil, err
	}
	if _, err := selectPhaseBRSAKey(body, "__key-id-probe-that-cannot-match__"); err == nil ||
		!strings.Contains(err.Error(), "key unavailable") {
		zero(body)
		return nil, fmt.Errorf("phase-b OIDC JWKS invalid")
	}
	return &phaseBGitHubKeySet{
		Issuer:       issuer,
		DiscoveryURL: phaseBGitHubDiscoveryURL,
		JWKSURL:      jwksURL,
		CanonicalURL: canonicalURL,
		Body:         body,
		BodyDigest:   sha256Digest(body),
	}, nil
}

func fetchPhaseBHTTPSJSON(ctx context.Context, rawURL string, maximum int64) ([]byte, string, error) {
	if maximum < 1 || maximum > phaseBMaximumJWKSBytes {
		return nil, "", fmt.Errorf("phase-b HTTPS response limit invalid")
	}
	parsed, err := url.Parse(rawURL)
	if err != nil || validatePhaseBGitHubHTTPSURL(rawURL) != nil {
		return nil, "", fmt.Errorf("phase-b HTTPS URL invalid")
	}
	transport := &http.Transport{
		Proxy:                 nil,
		DisableKeepAlives:     true,
		ForceAttemptHTTP2:     false,
		TLSHandshakeTimeout:   5 * time.Second,
		ResponseHeaderTimeout: 5 * time.Second,
		TLSClientConfig: &tls.Config{
			MinVersion: tls.VersionTLS12,
			ServerName: parsed.Hostname(),
		},
	}
	transport.DialContext = func(dialContext context.Context, network, address string) (net.Conn, error) {
		if network != "tcp" && network != "tcp4" && network != "tcp6" {
			return nil, fmt.Errorf("phase-b DNS network invalid")
		}
		host, port, splitErr := net.SplitHostPort(address)
		if splitErr != nil || !strings.EqualFold(host, parsed.Hostname()) || port != "443" {
			return nil, fmt.Errorf("phase-b DNS target invalid")
		}
		addresses, resolveErr := net.DefaultResolver.LookupNetIP(dialContext, "ip", host)
		if resolveErr != nil || len(addresses) == 0 {
			return nil, fmt.Errorf("phase-b DNS resolution failed")
		}
		sort.Slice(addresses, func(left, right int) bool {
			return addresses[left].String() < addresses[right].String()
		})
		var lastErr error
		for _, address := range addresses {
			if !phaseBPublicAddress(address) {
				continue
			}
			dialer := net.Dialer{Timeout: 5 * time.Second, KeepAlive: -1}
			connection, dialErr := dialer.DialContext(
				dialContext,
				"tcp",
				net.JoinHostPort(address.String(), port),
			)
			if dialErr == nil {
				return connection, nil
			}
			lastErr = dialErr
		}
		if lastErr != nil {
			return nil, fmt.Errorf("phase-b HTTPS connection failed")
		}
		return nil, fmt.Errorf("phase-b DNS resolved only disallowed addresses")
	}
	client := &http.Client{
		Transport: transport,
		Timeout:   phaseBHTTPTimeout,
		CheckRedirect: func(_ *http.Request, _ []*http.Request) error {
			return fmt.Errorf("phase-b HTTPS redirect forbidden")
		},
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, parsed.String(), nil)
	if err != nil {
		return nil, "", fmt.Errorf("phase-b HTTPS request invalid")
	}
	request.Header.Set("Accept", "application/json")
	response, err := client.Do(request)
	if err != nil {
		return nil, "", fmt.Errorf("phase-b HTTPS request failed")
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return nil, "", fmt.Errorf("phase-b HTTPS status invalid")
	}
	mediaType := strings.ToLower(strings.TrimSpace(strings.Split(response.Header.Get("Content-Type"), ";")[0]))
	if mediaType != "application/json" && mediaType != "application/jwk-set+json" {
		return nil, "", fmt.Errorf("phase-b HTTPS media type invalid")
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, maximum+1))
	if err != nil || len(body) < 1 || int64(len(body)) > maximum {
		zero(body)
		return nil, "", fmt.Errorf("phase-b HTTPS body invalid")
	}
	return body, parsed.String(), nil
}

func validatePhaseBGitHubHTTPSURL(raw string) error {
	parsed, err := url.Parse(raw)
	if err != nil || parsed.Scheme != "https" || parsed.Host != "token.actions.githubusercontent.com" ||
		parsed.User != nil || parsed.Fragment != "" || parsed.RawQuery != "" ||
		!strings.HasPrefix(parsed.Path, "/.well-known/") ||
		parsed.EscapedPath() != parsed.Path || parsed.RawPath != "" {
		return fmt.Errorf("phase-b GitHub URL invalid")
	}
	return nil
}

func phaseBPublicAddress(address netip.Addr) bool {
	if !address.IsValid() || !address.IsGlobalUnicast() || address.IsPrivate() || address.IsLoopback() ||
		address.IsLinkLocalUnicast() || address.IsLinkLocalMulticast() || address.IsMulticast() ||
		address.IsUnspecified() {
		return false
	}
	if address.Is4() {
		value := address.As4()
		if value[0] == 0 || value[0] == 127 || value[0] >= 224 ||
			(value[0] == 100 && value[1]&0xc0 == 64) ||
			(value[0] == 169 && value[1] == 254) ||
			(value[0] == 192 && value[1] == 0 && value[2] == 0) ||
			(value[0] == 192 && value[1] == 0 && value[2] == 2) ||
			(value[0] == 192 && value[1] == 88 && value[2] == 99) ||
			(value[0] == 198 && value[1]&0xfe == 18) ||
			(value[0] == 198 && value[1] == 51 && value[2] == 100) ||
			(value[0] == 203 && value[1] == 0 && value[2] == 113) {
			return false
		}
	} else {
		for _, prefix := range []netip.Prefix{
			netip.MustParsePrefix("2001:db8::/32"),
			netip.MustParsePrefix("2001:10::/28"),
			netip.MustParsePrefix("2001:20::/28"),
		} {
			if prefix.Contains(address) {
				return false
			}
		}
	}
	return true
}

func verifyPhaseBGitHubOIDC(
	token []byte,
	keySet *phaseBGitHubKeySet,
	policy *phaseBRootPolicy,
	now time.Time,
) (*phaseBVerifiedGitHubIdentity, error) {
	if len(token) < 1 || len(token) > phaseBMaximumOIDCBytes || keySet == nil || policy == nil ||
		keySet.Issuer != phaseBGitHubIssuer || keySet.DiscoveryURL != phaseBGitHubDiscoveryURL ||
		validatePhaseBGitHubHTTPSURL(keySet.JWKSURL) != nil || keySet.CanonicalURL != keySet.JWKSURL ||
		len(keySet.Body) < 1 || keySet.BodyDigest != sha256Digest(keySet.Body) || now.IsZero() {
		return nil, fmt.Errorf("phase-b OIDC inputs invalid")
	}
	segments := bytes.Split(token, []byte{'.'})
	if len(segments) != 3 || len(segments[0]) < 1 || len(segments[1]) < 1 || len(segments[2]) < 1 {
		return nil, fmt.Errorf("phase-b OIDC compact JWS invalid")
	}
	headerBytes, err := decodePhaseBBase64URL(segments[0], 4096)
	if err != nil {
		return nil, err
	}
	defer zero(headerBytes)
	headerValue, err := decodeStrictJSON(headerBytes)
	if err != nil {
		return nil, fmt.Errorf("phase-b OIDC header invalid")
	}
	header, ok := headerValue.(map[string]any)
	if !ok || !hasExactKeys(header, "alg", "kid", "typ") ||
		!exactStringEquals(header["alg"], "RS256") || !exactStringEquals(header["typ"], "JWT") {
		return nil, fmt.Errorf("phase-b OIDC header invalid")
	}
	keyID, ok := exactString(header["kid"])
	if !ok || len(keyID) < 1 || len(keyID) > 256 || strings.ContainsAny(keyID, "\x00\r\n") {
		return nil, fmt.Errorf("phase-b OIDC key ID invalid")
	}
	publicKey, err := selectPhaseBRSAKey(keySet.Body, keyID)
	if err != nil {
		return nil, err
	}
	signature, err := decodePhaseBBase64URL(segments[2], 8192)
	if err != nil {
		return nil, err
	}
	defer zero(signature)
	signed := make([]byte, 0, len(segments[0])+1+len(segments[1]))
	signed = append(signed, segments[0]...)
	signed = append(signed, '.')
	signed = append(signed, segments[1]...)
	digest := sha256.Sum256(signed)
	zero(signed)
	if err := rsa.VerifyPKCS1v15(publicKey, crypto.SHA256, digest[:], signature); err != nil {
		return nil, fmt.Errorf("phase-b OIDC signature invalid")
	}
	claimsBytes, err := decodePhaseBBase64URL(segments[1], phaseBMaximumOIDCBytes)
	if err != nil {
		return nil, err
	}
	defer zero(claimsBytes)
	claimsValue, err := decodeStrictJSON(claimsBytes)
	if err != nil {
		return nil, fmt.Errorf("phase-b OIDC claims invalid")
	}
	claims, ok := claimsValue.(map[string]any)
	if !ok {
		return nil, fmt.Errorf("phase-b OIDC claims invalid")
	}
	identity, err := phaseBIdentityFromClaims(claims, keyID, sha256Digest(token), keySet.BodyDigest)
	if err != nil {
		return nil, err
	}
	if err := validatePhaseBTokenTime(identity, policy, now); err != nil {
		return nil, err
	}
	if err := bindPhaseBIdentityToPolicy(identity, policy); err != nil {
		return nil, err
	}
	return identity, nil
}

func phaseBIdentityFromClaims(
	claims map[string]any,
	keyID string,
	tokenDigest string,
	keySetDigest string,
) (*phaseBVerifiedGitHubIdentity, error) {
	requiredStrings := []string{
		"iss", "aud", "sub", "repository", "repository_id", "repository_owner_id",
		"ref", "sha", "workflow_ref", "workflow_sha", "run_id", "run_attempt",
		"environment", "check_run_id", "jti",
	}
	values := make(map[string]string, len(requiredStrings))
	for _, name := range requiredStrings {
		value, ok := exactString(claims[name])
		if !ok || value == "" || len(value) > 2048 || strings.ContainsAny(value, "\x00\r\n") {
			return nil, fmt.Errorf("phase-b OIDC required claim invalid")
		}
		values[name] = value
	}
	if values["iss"] != phaseBGitHubIssuer || !requestSHA1Pattern.MatchString(values["sha"]) ||
		!requestSHA1Pattern.MatchString(values["workflow_sha"]) ||
		!decimalIdentifier(values["repository_id"]) || !decimalIdentifier(values["repository_owner_id"]) ||
		!decimalIdentifier(values["run_id"]) || !decimalIdentifier(values["check_run_id"]) {
		return nil, fmt.Errorf("phase-b OIDC identity claim invalid")
	}
	runAttempt, err := strconv.ParseInt(values["run_attempt"], 10, 64)
	if err != nil || runAttempt < 1 || strconv.FormatInt(runAttempt, 10) != values["run_attempt"] {
		return nil, fmt.Errorf("phase-b OIDC run attempt invalid")
	}
	issuedAt, ok := exactBoundedInt(claims["iat"], 0)
	if !ok {
		return nil, fmt.Errorf("phase-b OIDC issued-at invalid")
	}
	notBefore, ok := exactBoundedInt(claims["nbf"], 0)
	if !ok {
		return nil, fmt.Errorf("phase-b OIDC not-before invalid")
	}
	expiresAt, ok := exactBoundedInt(claims["exp"], 0)
	if !ok {
		return nil, fmt.Errorf("phase-b OIDC expiry invalid")
	}
	return &phaseBVerifiedGitHubIdentity{
		Audience:          values["aud"],
		Subject:           values["sub"],
		Repository:        values["repository"],
		RepositoryID:      values["repository_id"],
		RepositoryOwnerID: values["repository_owner_id"],
		Ref:               values["ref"],
		CandidateSHA:      values["sha"],
		WorkflowRef:       values["workflow_ref"],
		WorkflowSHA:       values["workflow_sha"],
		RunID:             values["run_id"],
		RunAttempt:        runAttempt,
		Environment:       values["environment"],
		CheckRunID:        values["check_run_id"],
		TokenID:           values["jti"],
		IssuedAt:          issuedAt,
		NotBefore:         notBefore,
		ExpiresAt:         expiresAt,
		KeyID:             keyID,
		TokenDigest:       tokenDigest,
		KeySetDigest:      keySetDigest,
	}, nil
}

func validatePhaseBTokenTime(identity *phaseBVerifiedGitHubIdentity, policy *phaseBRootPolicy, now time.Time) error {
	if identity == nil || policy == nil || identity.ExpiresAt <= identity.IssuedAt ||
		identity.NotBefore < identity.IssuedAt-phaseBClockSkewSeconds() ||
		identity.ExpiresAt-identity.IssuedAt > policy.MaxRequestTTL {
		return fmt.Errorf("phase-b OIDC lifetime invalid")
	}
	nowUnix := now.Unix()
	if identity.IssuedAt > nowUnix+phaseBClockSkewSeconds() ||
		identity.NotBefore > nowUnix+phaseBClockSkewSeconds() ||
		nowUnix >= identity.ExpiresAt-phaseBClockSkewSeconds() ||
		nowUnix-identity.IssuedAt > policy.MaxRequestTTL+phaseBClockSkewSeconds() {
		return fmt.Errorf("phase-b OIDC token not current")
	}
	return nil
}

func phaseBClockSkewSeconds() int64 { return int64(phaseBClockSkew / time.Second) }

func bindPhaseBIdentityToPolicy(identity *phaseBVerifiedGitHubIdentity, policy *phaseBRootPolicy) error {
	if identity == nil || policy == nil {
		return fmt.Errorf("phase-b identity binding unavailable")
	}
	expected := policy.Identity
	if identity.Audience != expected.Audience || identity.Repository != expected.Repository ||
		identity.RepositoryID != policy.RepositoryID || identity.RepositoryOwnerID != policy.RepositoryOwnerID ||
		identity.Ref != expected.Ref || identity.CandidateSHA != expected.CandidateSHA ||
		identity.WorkflowRef != expected.WorkflowRef || identity.WorkflowSHA != expected.WorkflowSHA ||
		identity.RunID != expected.RunID || identity.RunAttempt != expected.RunAttempt ||
		identity.Environment != expected.Environment || identity.CheckRunID != policy.CheckRunID {
		return fmt.Errorf("phase-b OIDC root-policy identity mismatch")
	}
	if identity.Subject != policy.Subject || !validPhaseBPolicySubject(
		identity.Subject,
		identity.Repository,
		identity.RepositoryOwnerID,
		identity.RepositoryID,
		identity.Environment,
	) {
		return fmt.Errorf("phase-b OIDC subject mismatch")
	}
	return nil
}

func validPhaseBPolicySubject(subject, repository, ownerID, repositoryID, environment string) bool {
	if subject == "" || len(subject) > 2048 || strings.ContainsAny(subject, "\x00\r\n") {
		return false
	}
	repositoryParts := strings.Split(repository, "/")
	if len(repositoryParts) != 2 || repositoryParts[0] == "" || repositoryParts[1] == "" {
		return false
	}
	escapedEnvironment := strings.ReplaceAll(environment, ":", "%3A")
	legacyPrefix := "repo:" + repository + ":"
	immutablePrefix := "repo:" + repositoryParts[0] + "@" + ownerID + "/" +
		repositoryParts[1] + "@" + repositoryID + ":"
	context := "environment:" + escapedEnvironment
	return subject == legacyPrefix+context || subject == immutablePrefix+context
}

func decodePhaseBBase64URL(encoded []byte, maximum int) ([]byte, error) {
	if len(encoded) < 1 || len(encoded) > maximum*2 || bytes.ContainsRune(encoded, '=') {
		return nil, fmt.Errorf("phase-b base64url invalid")
	}
	decoded, err := base64.RawURLEncoding.DecodeString(string(encoded))
	if err != nil || len(decoded) < 1 || len(decoded) > maximum ||
		base64.RawURLEncoding.EncodeToString(decoded) != string(encoded) {
		zero(decoded)
		return nil, fmt.Errorf("phase-b base64url invalid")
	}
	return decoded, nil
}

func selectPhaseBRSAKey(raw []byte, selectedKeyID string) (*rsa.PublicKey, error) {
	if len(raw) < 1 || len(raw) > phaseBMaximumJWKSBytes || selectedKeyID == "" {
		return nil, fmt.Errorf("phase-b JWKS invalid")
	}
	value, err := decodeStrictJSON(raw)
	if err != nil {
		return nil, fmt.Errorf("phase-b JWKS invalid")
	}
	outer, ok := value.(map[string]any)
	if !ok || !hasExactKeys(outer, "keys") {
		return nil, fmt.Errorf("phase-b JWKS invalid")
	}
	items, ok := outer["keys"].([]any)
	if !ok || len(items) < 1 || len(items) > 64 {
		return nil, fmt.Errorf("phase-b JWKS invalid")
	}
	seen := make(map[string]struct{}, len(items))
	var selected *rsa.PublicKey
	for _, item := range items {
		object, ok := item.(map[string]any)
		if !ok {
			return nil, fmt.Errorf("phase-b JWK invalid")
		}
		keyID, ok := exactString(object["kid"])
		if !ok || keyID == "" || len(keyID) > 256 {
			return nil, fmt.Errorf("phase-b JWK key ID invalid")
		}
		if _, duplicate := seen[keyID]; duplicate {
			return nil, fmt.Errorf("phase-b JWK key ID duplicate")
		}
		seen[keyID] = struct{}{}
		if keyID != selectedKeyID {
			continue
		}
		if !exactStringEquals(object["kty"], "RSA") ||
			(object["use"] != nil && !exactStringEquals(object["use"], "sig")) ||
			(object["alg"] != nil && !exactStringEquals(object["alg"], "RS256")) {
			return nil, fmt.Errorf("phase-b JWK algorithm invalid")
		}
		modulusText, modulusOK := exactString(object["n"])
		exponentText, exponentOK := exactString(object["e"])
		if !modulusOK || !exponentOK {
			return nil, fmt.Errorf("phase-b JWK parameters invalid")
		}
		modulusBytes, err := decodePhaseBBase64URL([]byte(modulusText), 1024)
		if err != nil {
			return nil, fmt.Errorf("phase-b JWK modulus invalid")
		}
		modulus := new(big.Int).SetBytes(modulusBytes)
		zero(modulusBytes)
		exponentBytes, err := decodePhaseBBase64URL([]byte(exponentText), 8)
		if err != nil || len(exponentBytes) > 4 || exponentBytes[0] == 0 {
			zero(exponentBytes)
			return nil, fmt.Errorf("phase-b JWK exponent invalid")
		}
		exponent := 0
		for _, value := range exponentBytes {
			exponent = exponent<<8 | int(value)
		}
		zero(exponentBytes)
		if modulus.BitLen() < 2048 || modulus.BitLen() > 4096 || modulus.Bit(0) == 0 ||
			exponent < 3 || exponent > 1<<31-1 || exponent&1 == 0 {
			return nil, fmt.Errorf("phase-b JWK strength invalid")
		}
		selected = &rsa.PublicKey{N: modulus, E: exponent}
	}
	if selected == nil {
		return nil, fmt.Errorf("phase-b JWK key unavailable")
	}
	return selected, nil
}

func decimalIdentifier(value string) bool {
	if value == "" || (len(value) > 1 && value[0] == '0') {
		return false
	}
	for _, character := range value {
		if character < '0' || character > '9' {
			return false
		}
	}
	return true
}
