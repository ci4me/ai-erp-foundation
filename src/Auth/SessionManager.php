<?php
declare(strict_types=1);

namespace App\Auth;

/**
 * Stateless-token-style session manager backed by an in-memory store.
 * Issues opaque random session IDs, validates them, supports explicit logout
 * and time-based expiry. Self-contained so it runs under the `php` CLI.
 */
final class SessionManager
{
    /** @var array<string, array{user_id:int,email:string,expires_at:int}> */
    private array $sessions = [];

    private int $ttlSeconds;

    /** @var callable():int returns current unix time; injectable for tests */
    private $clock;

    /**
     * @param int $ttlSeconds session lifetime; default 1 hour
     * @param (callable():int)|null $clock injectable clock for deterministic tests
     */
    public function __construct(int $ttlSeconds = 3600, ?callable $clock = null)
    {
        if ($ttlSeconds <= 0) {
            throw new \InvalidArgumentException('TTL must be positive.');
        }
        $this->ttlSeconds = $ttlSeconds;
        $this->clock = $clock ?? static fn (): int => time();
    }

    /**
     * Create a new session for a user. Returns the opaque session token.
     */
    public function create(int $userId, string $email): string
    {
        $token = bin2hex(random_bytes(32));
        $now = ($this->clock)();
        $this->sessions[$token] = [
            'user_id' => $userId,
            'email' => $email,
            'expires_at' => $now + $this->ttlSeconds,
        ];

        return $token;
    }

    /**
     * Validate a token. Returns the session payload if valid and unexpired,
     * null otherwise. Expired sessions are garbage-collected on access.
     *
     * @return array{user_id:int,email:string,expires_at:int}|null
     */
    public function validate(string $token): ?array
    {
        $session = $this->sessions[$token] ?? null;
        if ($session === null) {
            return null;
        }

        if (($this->clock)() >= $session['expires_at']) {
            unset($this->sessions[$token]);
            return null;
        }

        return $session;
    }

    public function isValid(string $token): bool
    {
        return $this->validate($token) !== null;
    }

    /**
     * Explicitly destroy a session (logout). Returns true if a session existed.
     */
    public function destroy(string $token): bool
    {
        if (!isset($this->sessions[$token])) {
            return false;
        }
        unset($this->sessions[$token]);
        return true;
    }

    public function activeCount(): int
    {
        return count($this->sessions);
    }
}
