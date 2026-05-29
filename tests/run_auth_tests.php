<?php
declare(strict_types=1);

/**
 * Self-contained, dependency-free test runner for the Auth subsystem.
 *
 * Usage:  php tests/run_auth_tests.php
 * Exits 0 if all assertions pass, 1 (non-zero) on the first failure summary.
 *
 * No PHPUnit, no Composer — just the `php` CLI.
 */

namespace App\Auth\Tests;

use App\Auth\Auth;
use App\Auth\PasswordHasher;
use App\Auth\SessionManager;
use App\Auth\StubOAuthProvider;
use App\Auth\UserStore;

$root = dirname(__DIR__);
require $root . '/src/Auth/PasswordHasher.php';
require $root . '/src/Auth/UserStore.php';
require $root . '/src/Auth/SessionManager.php';
require $root . '/src/Auth/OAuthProvider.php';
require $root . '/src/Auth/StubOAuthProvider.php';
require $root . '/src/Auth/Auth.php';

$tests = 0;
$failures = [];

function check(string $label, bool $cond, array &$failures, int &$tests): void
{
    $tests++;
    if ($cond) {
        fwrite(STDOUT, "  PASS: {$label}\n");
    } else {
        $failures[] = $label;
        fwrite(STDOUT, "  FAIL: {$label}\n");
    }
}

/** Assert that $fn throws an exception of (sub)type $type. */
function checkThrows(string $label, string $type, callable $fn, array &$failures, int &$tests): void
{
    $threw = false;
    try {
        $fn();
    } catch (\Throwable $e) {
        $threw = $e instanceof $type;
    }
    check($label, $threw, $failures, $tests);
}

// --- AC1: password hashing + registration/login ---
echo "[AC1] Password hashing + email/password auth\n";

$hasher = new PasswordHasher();
$hash = $hasher->hash('correct horse battery');
check('hash is non-empty and not plaintext', $hash !== '' && $hash !== 'correct horse battery', $failures, $tests);
check('hash starts with a bcrypt/argon marker', str_starts_with($hash, '$'), $failures, $tests);
check('verify accepts correct password', $hasher->verify('correct horse battery', $hash), $failures, $tests);
check('verify rejects wrong password', !$hasher->verify('wrong', $hash), $failures, $tests);
checkThrows('hashing empty password throws', \InvalidArgumentException::class, fn () => $hasher->hash(''), $failures, $tests);

$store = new UserStore($hasher);
$user = $store->register('Alice@Example.com', 'sup3rsecret');
check('register returns id', $user['id'] === 1, $failures, $tests);
check('register normalizes email to lowercase', $user['email'] === 'alice@example.com', $failures, $tests);
checkThrows('duplicate registration rejected', \InvalidArgumentException::class, fn () => $store->register('alice@example.com', 'sup3rsecret'), $failures, $tests);
checkThrows('invalid email rejected', \InvalidArgumentException::class, fn () => $store->register('not-an-email', 'sup3rsecret'), $failures, $tests);
checkThrows('short password rejected', \InvalidArgumentException::class, fn () => $store->register('bob@example.com', 'short'), $failures, $tests);

check('authenticate accepts correct credentials', $store->authenticate('alice@example.com', 'sup3rsecret') !== null, $failures, $tests);
check('authenticate rejects wrong password', $store->authenticate('alice@example.com', 'nope') === null, $failures, $tests);
check('authenticate rejects unknown user', $store->authenticate('ghost@example.com', 'whatever') === null, $failures, $tests);

// --- AC2: session issuance + validation + expiry + logout ---
echo "[AC2] Session lifecycle\n";

$now = 1_000_000;
$clock = function () use (&$now): int { return $now; };
$sessions = new SessionManager(60, $clock);

$token = $sessions->create($user['id'], $user['email']);
check('session token issued', is_string($token) && strlen($token) >= 32, $failures, $tests);
check('valid session validates', $sessions->isValid($token), $failures, $tests);
$payload = $sessions->validate($token);
check('session payload carries user id', $payload !== null && $payload['user_id'] === $user['id'], $failures, $tests);

check('unknown token is invalid', !$sessions->isValid('deadbeef'), $failures, $tests);

// expiry
$now += 61; // advance past the 60s TTL
check('expired session is invalid', !$sessions->isValid($token), $failures, $tests);
check('expired session is garbage-collected', $sessions->activeCount() === 0, $failures, $tests);

// logout
$now = 2_000_000;
$token2 = $sessions->create($user['id'], $user['email']);
check('logout destroys an existing session', $sessions->destroy($token2), $failures, $tests);
check('session invalid after logout', !$sessions->isValid($token2), $failures, $tests);
check('logout of unknown token returns false', !$sessions->destroy('nope'), $failures, $tests);

// --- AC3: OAuth stub via pluggable interface ---
echo "[AC3] OAuth stub provider\n";

$provider = new StubOAuthProvider('github');
check('provider exposes name', $provider->name() === 'github', $failures, $tests);
check('authorization url contains state', str_contains($provider->authorizationUrl('xyz-state'), 'xyz-state'), $failures, $tests);

$profile = $provider->fetchUser('valid-code');
check('stub returns a user profile', $profile['email'] === 'oauth.user@example.com', $failures, $tests);
check('profile carries provider name', $profile['provider'] === 'github', $failures, $tests);
checkThrows('invalid oauth code throws', \RuntimeException::class, fn () => $provider->fetchUser('bogus'), $failures, $tests);

// --- Facade integration: ties AC1-AC3 together ---
echo "[FACADE] End-to-end via Auth facade\n";

$auth = new Auth();
$auth->registerOAuthProvider(new StubOAuthProvider('google'));

$auth->register('carol@example.com', 'p@ssw0rd123');
$loginToken = $auth->login('carol@example.com', 'p@ssw0rd123');
check('facade login returns token on success', is_string($loginToken), $failures, $tests);
check('facade login returns null on bad password', $auth->login('carol@example.com', 'wrong') === null, $failures, $tests);
check('facade session validates', $auth->validateSession((string) $loginToken) !== null, $failures, $tests);
check('facade logout works', $auth->logout((string) $loginToken), $failures, $tests);
check('facade session invalid after logout', $auth->validateSession((string) $loginToken) === null, $failures, $tests);

$oauthToken = $auth->loginWithOAuth('google', 'valid-code');
check('oauth login returns session token', is_string($oauthToken) && $auth->validateSession($oauthToken) !== null, $failures, $tests);
checkThrows('oauth login with unknown provider throws', \InvalidArgumentException::class, fn () => $auth->loginWithOAuth('facebook', 'valid-code'), $failures, $tests);
checkThrows('oauth login with bad code throws', \RuntimeException::class, fn () => $auth->loginWithOAuth('google', 'bogus'), $failures, $tests);

// --- summary ---
echo "\n";
$failed = count($failures);
$passed = $tests - $failed;
echo "Ran {$tests} assertions: {$passed} passed, {$failed} failed.\n";

if ($failed > 0) {
    echo "FAILURES:\n";
    foreach ($failures as $f) {
        echo "  - {$f}\n";
    }
    exit(1);
}

echo "ALL TESTS PASSED\n";
exit(0);
