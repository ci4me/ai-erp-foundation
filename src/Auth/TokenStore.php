<?php
declare(strict_types=1);

namespace App\Auth;

/**
 * Expiring, single-use, purpose-bound token store.
 *
 * Shared primitive behind password reset and email verification. Issues a
 * high-entropy opaque token, stores only its HASH (never the raw token) keyed
 * by that hash, binds it to a purpose, and lets it be consumed exactly once
 * before it expires. Self-contained (in-memory) so it runs under the bare
 * `php` CLI; a persistent backend implements the same surface.
 *
 * Security properties (see epic #181 consensus):
 * - >=256-bit tokens (`random_bytes(32)`); only `hash('sha256', token)` stored.
 * - Purpose-bound: a `verify` token can never satisfy a `reset` consume.
 * - Single-use: consume marks `consumed_at` atomically; a second consume fails.
 * - Expiring: a token past its TTL is rejected (and garbage-collected on access).
 */
final class TokenStore
{
    /** @var array<string, array{user_id:int,purpose:string,expires_at:int,consumed_at:?int}> keyed by token hash */
    private array $tokens = [];

    private int $ttlSeconds;

    /** @var callable():int returns current unix time; injectable for tests */
    private $clock;

    /**
     * @param int $ttlSeconds token lifetime; default 15 minutes
     * @param (callable():int)|null $clock injectable clock for deterministic tests
     */
    public function __construct(int $ttlSeconds = 900, ?callable $clock = null)
    {
        if ($ttlSeconds <= 0) {
            throw new \InvalidArgumentException('TTL must be positive.');
        }
        $this->ttlSeconds = $ttlSeconds;
        $this->clock = $clock ?? static fn (): int => time();
    }

    /**
     * Issue a token for a user + purpose. Returns the opaque raw token; only its
     * hash is retained.
     */
    public function issue(int $userId, string $purpose): string
    {
        if ($purpose === '') {
            throw new \InvalidArgumentException('Token purpose must not be empty.');
        }
        $raw = bin2hex(random_bytes(32));
        $now = ($this->clock)();
        $this->tokens[$this->fingerprint($raw)] = [
            'user_id' => $userId,
            'purpose' => $purpose,
            'expires_at' => $now + $this->ttlSeconds,
            'consumed_at' => null,
        ];

        return $raw;
    }

    /**
     * Consume a token for a given purpose. Returns the owning user id on success,
     * null if the token is unknown, the purpose does not match, it is already
     * consumed, or it has expired. Single-use: a successful consume cannot be
     * repeated.
     */
    public function consume(string $rawToken, string $purpose): ?int
    {
        if ($rawToken === '' || $purpose === '') {
            return null;
        }
        $key = $this->fingerprint($rawToken);
        $record = $this->tokens[$key] ?? null;
        if ($record === null) {
            return null;
        }
        if (!hash_equals($record['purpose'], $purpose)) {
            return null;
        }
        $now = ($this->clock)();
        if ($now >= $record['expires_at']) {
            unset($this->tokens[$key]); // garbage-collect expired token
            return null;
        }
        if ($record['consumed_at'] !== null) {
            return null; // already used
        }

        // Atomic single-use: mark consumed before returning.
        $this->tokens[$key]['consumed_at'] = $now;

        return $record['user_id'];
    }

    /**
     * True iff a token is currently valid for the given purpose (does not
     * consume it).
     */
    public function isValid(string $rawToken, string $purpose): bool
    {
        $record = $this->tokens[$this->fingerprint($rawToken)] ?? null;
        if ($record === null || !hash_equals($record['purpose'], $purpose)) {
            return false;
        }
        return $record['consumed_at'] === null && ($this->clock)() < $record['expires_at'];
    }

    /**
     * Invalidate every outstanding token for a user (e.g. on account deletion or
     * password change). Returns the number of tokens removed.
     */
    public function revokeAllForUser(int $userId): int
    {
        $removed = 0;
        foreach ($this->tokens as $key => $record) {
            if ($record['user_id'] === $userId) {
                unset($this->tokens[$key]);
                $removed++;
            }
        }
        return $removed;
    }

    /** Number of stored (issued, not yet GC'd) tokens — for tests/observability. */
    public function count(): int
    {
        return count($this->tokens);
    }

    private function fingerprint(string $rawToken): string
    {
        return hash('sha256', $rawToken);
    }
}
