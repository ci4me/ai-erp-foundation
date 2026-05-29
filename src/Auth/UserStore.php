<?php
declare(strict_types=1);

namespace App\Auth;

/**
 * In-memory user repository. Self-contained (no DB dependency) so the auth
 * system runs and tests under the bare `php` CLI. In production this would be
 * swapped for a PDO-backed implementation behind the same method surface.
 *
 * Stores only the password HASH, never the plaintext.
 */
final class UserStore
{
    private PasswordHasher $hasher;

    /** @var array<string, array{id:int,email:string,hash:string}> keyed by lowercased email */
    private array $usersByEmail = [];

    private int $nextId = 1;

    public function __construct(?PasswordHasher $hasher = null)
    {
        $this->hasher = $hasher ?? new PasswordHasher();
    }

    /**
     * Register a new user with a hashed password.
     *
     * @return array{id:int,email:string} the created user (no hash exposed)
     * @throws \InvalidArgumentException on bad email or duplicate registration
     */
    public function register(string $email, string $password): array
    {
        $email = $this->normalizeEmail($email);

        if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
            throw new \InvalidArgumentException('Invalid email address.');
        }
        if (strlen($password) < 8) {
            throw new \InvalidArgumentException('Password must be at least 8 characters.');
        }
        if (isset($this->usersByEmail[$email])) {
            throw new \InvalidArgumentException('Email already registered.');
        }

        $id = $this->nextId++;
        $this->usersByEmail[$email] = [
            'id' => $id,
            'email' => $email,
            'hash' => $this->hasher->hash($password),
        ];

        return ['id' => $id, 'email' => $email];
    }

    /**
     * Verify credentials. Returns the user record on success, null otherwise.
     * Does not reveal whether it was the email or the password that was wrong.
     *
     * @return array{id:int,email:string}|null
     */
    public function authenticate(string $email, string $password): ?array
    {
        $email = $this->normalizeEmail($email);
        $record = $this->usersByEmail[$email] ?? null;

        if ($record === null) {
            // Run a dummy verify to keep timing roughly constant against
            // user-enumeration attacks.
            $this->hasher->verify($password, '$2y$10$usesomesillystringforsalt0000000000000000000000000000000');
            return null;
        }

        if (!$this->hasher->verify($password, $record['hash'])) {
            return null;
        }

        return ['id' => $record['id'], 'email' => $record['email']];
    }

    /**
     * Idempotent upsert used by OAuth flows: find by email or create a user
     * with a random unusable-by-password placeholder.
     *
     * @return array{id:int,email:string}
     */
    public function findOrCreateByEmail(string $email): array
    {
        $email = $this->normalizeEmail($email);
        if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
            throw new \InvalidArgumentException('Invalid email address.');
        }

        if (isset($this->usersByEmail[$email])) {
            $r = $this->usersByEmail[$email];
            return ['id' => $r['id'], 'email' => $r['email']];
        }

        $id = $this->nextId++;
        // Random hash that no plaintext password can match.
        $this->usersByEmail[$email] = [
            'id' => $id,
            'email' => $email,
            'hash' => $this->hasher->hash(bin2hex(random_bytes(32))),
        ];

        return ['id' => $id, 'email' => $email];
    }

    public function exists(string $email): bool
    {
        return isset($this->usersByEmail[$this->normalizeEmail($email)]);
    }

    private function normalizeEmail(string $email): string
    {
        return strtolower(trim($email));
    }
}
