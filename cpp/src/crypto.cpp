#include "crypto.hpp"

#include <openssl/bio.h>
#include <openssl/err.h>
#include <openssl/pem.h>
#include <openssl/rsa.h>

#include <stdexcept>
#include <vector>

namespace kalshi {

namespace {

[[noreturn]] void throw_openssl(const std::string& what) {
    char buf[256];
    unsigned long code = ERR_get_error();
    ERR_error_string_n(code, buf, sizeof(buf));
    throw std::runtime_error(what + ": " + buf);
}

}  // namespace

PKeyPtr load_private_key_pem(const std::string& pem) {
    BIO* bio = BIO_new_mem_buf(pem.data(), static_cast<int>(pem.size()));
    if (!bio) throw_openssl("BIO_new_mem_buf");
    EVP_PKEY* key = PEM_read_bio_PrivateKey(bio, nullptr, nullptr, nullptr);
    BIO_free(bio);
    if (!key) throw_openssl("PEM_read_bio_PrivateKey");
    return PKeyPtr(key, &EVP_PKEY_free);
}

std::string base64_encode(const unsigned char* data, size_t len) {
    // EVP_EncodeBlock writes 4 base64 chars per 3 input bytes (rounded up) plus a NUL.
    std::string out;
    out.resize(4 * ((len + 2) / 3) + 1);
    int n = EVP_EncodeBlock(reinterpret_cast<unsigned char*>(&out[0]), data, static_cast<int>(len));
    out.resize(n);
    return out;
}

std::string rsa_pss_sign_base64(EVP_PKEY* key, const std::string& message, PssSaltLen salt) {
    EVP_MD_CTX* ctx = EVP_MD_CTX_new();
    if (!ctx) throw_openssl("EVP_MD_CTX_new");

    EVP_PKEY_CTX* pctx = nullptr;
    if (EVP_DigestSignInit(ctx, &pctx, EVP_sha256(), nullptr, key) <= 0) {
        EVP_MD_CTX_free(ctx);
        throw_openssl("EVP_DigestSignInit");
    }
    if (EVP_PKEY_CTX_set_rsa_padding(pctx, RSA_PKCS1_PSS_PADDING) <= 0) {
        EVP_MD_CTX_free(ctx);
        throw_openssl("EVP_PKEY_CTX_set_rsa_padding");
    }
    const int salt_len = (salt == PssSaltLen::Digest) ? RSA_PSS_SALTLEN_DIGEST : RSA_PSS_SALTLEN_MAX;
    if (EVP_PKEY_CTX_set_rsa_pss_saltlen(pctx, salt_len) <= 0) {
        EVP_MD_CTX_free(ctx);
        throw_openssl("EVP_PKEY_CTX_set_rsa_pss_saltlen");
    }

    size_t sig_len = 0;
    if (EVP_DigestSign(ctx, nullptr, &sig_len,
                       reinterpret_cast<const unsigned char*>(message.data()), message.size()) <= 0) {
        EVP_MD_CTX_free(ctx);
        throw_openssl("EVP_DigestSign (size)");
    }
    std::vector<unsigned char> sig(sig_len);
    if (EVP_DigestSign(ctx, sig.data(), &sig_len,
                       reinterpret_cast<const unsigned char*>(message.data()), message.size()) <= 0) {
        EVP_MD_CTX_free(ctx);
        throw_openssl("EVP_DigestSign");
    }
    EVP_MD_CTX_free(ctx);
    return base64_encode(sig.data(), sig_len);
}

}  // namespace kalshi
