<?php
declare(strict_types=1);

namespace App\Auth;

/**
 * High-level authentication facade tying together password auth, sessions and
 * OAuth providers. This is the surface application code should depend on.
 */
final class Auth
{
    private UserStore $users;
    private SessionManager $sessions;

    /** @var array<string, OAuthProvider> keyed by provider name */
    private array $oauthProviders = [];

    public function __construct(?UserStore $users = null, ?SessionManager $sessions = null)
    {
        $this->users = $users ?? new UserStore();
        $this->sessions = $sessions ?? new SessionManager();
    }

    public function registerOAuthProvider(OAuthProvider $provider): void
    {
        $this->oauthProviders[$provider->name()] = $provider;
    }

    /**
     * @return array{id:int,email:string}
     */
    public function register(string $email, string $password): array
    {
        return $this->users->register($email, $password);
    }

    /**
     * Email/password login. Returns a session token on success, null on bad
     * credentials.
     */
    public function login(string $email, string $password): ?string
    {
        $user = $this->users->authenticate($email, $password);
        if ($user === null) {
            return null;
        }

        return $this->sessions->create($user['id'], $user['email']);
    }

    /**
     * Log in (or auto-provision) a user via an OAuth provider's auth code.
     * Returns a session token. Throws if the provider is unknown or the code
     * is invalid.
     */
    public function loginWithOAuth(string $providerName, string $code): string
    {
        $provider = $this->oauthProviders[$providerName] ?? null;
        if ($provider === null) {
            throw new \InvalidArgumentException("Unknown OAuth provider: {$providerName}");
        }

        $profile = $provider->fetchUser($code); // may throw on invalid code
        $user = $this->users->findOrCreateByEmail($profile['email']);

        return $this->sessions->create($user['id'], $user['email']);
    }

    /**
     * @return array{user_id:int,email:string,expires_at:int}|null
     */
    public function validateSession(string $token): ?array
    {
        return $this->sessions->validate($token);
    }

    /**
     * Log out a session. Returns true if a session was destroyed.
     */
    public function logout(string $token): bool
    {
        return $this->sessions->destroy($token);
    }
}
