#pragma once

#include <openssl/evp.h>

#include <memory>
#include <string>

namespace kalshi {

// RAII wrapper around EVP_PKEY.
using PKeyPtr = std::unique_ptr<EVP_PKEY, decltype(&EVP_PKEY_free)>;

// Loads an RSA private key from a PEM string (PKCS#8 or PKCS#1).  Throws std::runtime_error.
PKeyPtr load_private_key_pem(const std::string& pem);

// Salt-length selector mirroring the python `cryptography` library constants used in the
// original code: kalshi_feed.py signs with DIGEST_LENGTH, kalshi_http_gateway.py with MAX_LENGTH.
enum class PssSaltLen { Digest, Max };

// Signs `message` with RSA-PSS / SHA-256 and returns the base64-encoded signature.
std::string rsa_pss_sign_base64(EVP_PKEY* key, const std::string& message, PssSaltLen salt);

std::string base64_encode(const unsigned char* data, size_t len);

}  // namespace kalshi
