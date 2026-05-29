<?php
declare(strict_types=1);

namespace App\Auth;

/**
 * Wraps PHP's native password hashing so the rest of the auth system never
 * touches raw hashing primitives. Uses PASSWORD_DEFAULT (bcrypt today,
 * may become argon2 in future PHP versions) so hashes stay future-proof.
 */
final class PasswordHasher
{
    /** @var string|int A PASSWORD_* algorithm identifier. */
    private string|int $algo;

    /**
     * @param string|int $algo A PASSWORD_* constant. Defaults to PASSWORD_DEFAULT.
     */
    public function __construct(string|int $algo = PASSWORD_DEFAULT)
    {
        $this->algo = $algo;
    }

    /**
     * Hash a plaintext password. Never store the result of this with the
     * plaintext alongside it.
     */
    public function hash(string $plain): string
    {
        if ($plain === '') {
            throw new \InvalidArgumentException('Password must not be empty.');
        }

        $hash = password_hash($plain, $this->algo);
        if (!is_string($hash) || $hash === '') {
            throw new \RuntimeException('Password hashing failed.');
        }

        return $hash;
    }

    /**
     * Constant-time verification of a plaintext password against a stored hash.
     */
    public function verify(string $plain, string $hash): bool
    {
        if ($plain === '' || $hash === '') {
            return false;
        }

        return password_verify($plain, $hash);
    }

    /**
     * Whether a stored hash should be re-hashed (e.g. cost or algo changed).
     */
    public function needsRehash(string $hash): bool
    {
        return password_needs_rehash($hash, $this->algo);
    }
}
