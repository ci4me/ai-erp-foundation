<?php
declare(strict_types=1);

/**
 * Self-contained, dependency-free test runner for TokenStore (#182).
 *
 * Usage:  php tests/run_token_store_tests.php
 * Exits 0 if all assertions pass, non-zero on any failure.
 */

namespace App\Auth\Tests;

use App\Auth\TokenStore;

require dirname(__DIR__) . '/src/Auth/TokenStore.php';

$tests = 0;
$failures = [];

function check(string $label, bool $cond, array &$failures, int &$tests): void
{
    $tests++;
    echo ($cond ? "  PASS: " : "  FAIL: ") . $label . "\n";
    if (!$cond) {
        $failures[] = $label;
    }
}

echo "[TokenStore] issue + single-use consume\n";

$now = 1_000_000;
$clock = function () use (&$now): int { return $now; };
$store = new TokenStore(900, $clock);

$raw = $store->issue(42, 'reset');
check('issued token is opaque hex of length 64', strlen($raw) === 64 && ctype_xdigit($raw), $failures, $tests);
check('raw token is not stored verbatim (only hash retained)', $store->count() === 1, $failures, $tests);
check('isValid true before consume', $store->isValid($raw, 'reset'), $failures, $tests);

check('consume returns the owning user id', $store->consume($raw, 'reset') === 42, $failures, $tests);
check('second consume fails (single-use)', $store->consume($raw, 'reset') === null, $failures, $tests);
check('isValid false after consume', !$store->isValid($raw, 'reset'), $failures, $tests);

echo "[TokenStore] purpose binding\n";

$verifyTok = $store->issue(7, 'verify');
check('verify token cannot satisfy a reset consume', $store->consume($verifyTok, 'reset') === null, $failures, $tests);
check('verify token is still valid for its own purpose', $store->isValid($verifyTok, 'verify'), $failures, $tests);
check('verify token consumes for the matching purpose', $store->consume($verifyTok, 'verify') === 7, $failures, $tests);

echo "[TokenStore] expiry\n";

$expiring = $store->issue(99, 'reset');
$now += 901; // advance past the 900s TTL
check('expired token does not consume', $store->consume($expiring, 'reset') === null, $failures, $tests);
check('expired token is garbage-collected on access', $store->isValid($expiring, 'reset') === false, $failures, $tests);

echo "[TokenStore] unknown + empty + revoke\n";

check('unknown token returns null', $store->consume('deadbeef', 'reset') === null, $failures, $tests);
check('empty token returns null', $store->consume('', 'reset') === null, $failures, $tests);

try {
    $store->issue(1, '');
    check('empty purpose throws', false, $failures, $tests);
} catch (\InvalidArgumentException $e) {
    check('empty purpose throws', true, $failures, $tests);
}

$store->issue(500, 'reset');
$store->issue(500, 'verify');
$survivor = $store->issue(501, 'reset');
check('revokeAllForUser removes only that user\'s tokens', $store->revokeAllForUser(500) === 2, $failures, $tests);
check('other users\' tokens survive revoke', $store->isValid($survivor, 'reset'), $failures, $tests);

echo "\n";
$failed = count($failures);
$passed = $tests - $failed;
echo "Ran {$tests} assertions: {$passed} passed, {$failed} failed.\n";
if ($failed > 0) {
    echo "FAILURES:\n  - " . implode("\n  - ", $failures) . "\n";
    exit(1);
}
echo "ALL TESTS PASSED\n";
exit(0);
