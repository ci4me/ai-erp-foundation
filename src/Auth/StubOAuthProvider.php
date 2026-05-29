<?php
declare(strict_types=1);

namespace App\Auth;

/**
 * Network-free OAuth provider used for local development and tests.
 *
 * Instead of calling a real identity provider, it resolves authorization
 * codes from an in-memory map. A known code yields a profile; an unknown
 * code throws, exercising the failure path. This proves the pluggable
 * interface without any external dependency.
 */
final class StubOAuthProvider implements OAuthProvider
{
    private string $providerName;

    /** @var array<string, array{provider_id:string,email:string,name:string}> */
    private array $codeToProfile;

    /**
     * @param array<string, array{provider_id:string,email:string,name:string}> $codeToProfile
     */
    public function __construct(string $providerName = 'stub', array $codeToProfile = [])
    {
        $this->providerName = $providerName;

        // Provide a default known code so the happy path works out of the box.
        if ($codeToProfile === []) {
            $codeToProfile = [
                'valid-code' => [
                    'provider_id' => 'stub-user-1',
                    'email' => 'oauth.user@example.com',
                    'name' => 'OAuth User',
                ],
            ];
        }
        $this->codeToProfile = $codeToProfile;
    }

    public function name(): string
    {
        return $this->providerName;
    }

    public function authorizationUrl(string $state): string
    {
        return sprintf(
            'https://oauth.example.test/%s/authorize?state=%s',
            rawurlencode($this->providerName),
            rawurlencode($state)
        );
    }

    public function fetchUser(string $code): array
    {
        $profile = $this->codeToProfile[$code] ?? null;
        if ($profile === null) {
            throw new \RuntimeException('Invalid or expired authorization code.');
        }

        return [
            'provider' => $this->providerName,
            'provider_id' => $profile['provider_id'],
            'email' => $profile['email'],
            'name' => $profile['name'],
        ];
    }
}
