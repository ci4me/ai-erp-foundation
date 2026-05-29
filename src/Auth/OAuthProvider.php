<?php
declare(strict_types=1);

namespace App\Auth;

/**
 * Pluggable OAuth provider contract. Concrete providers (Google, GitHub, ...)
 * implement this. The auth facade depends only on this interface so providers
 * can be swapped without touching login logic.
 */
interface OAuthProvider
{
    /**
     * Short machine name of the provider, e.g. "google", "github".
     */
    public function name(): string;

    /**
     * Build the URL the user is redirected to in order to start the OAuth
     * dance. `state` is an anti-CSRF nonce the caller must validate on return.
     */
    public function authorizationUrl(string $state): string;

    /**
     * Exchange an authorization code for a normalized user profile.
     *
     * @return array{provider:string,provider_id:string,email:string,name:string}
     * @throws \RuntimeException if the code is invalid / exchange fails
     */
    public function fetchUser(string $code): array;
}
