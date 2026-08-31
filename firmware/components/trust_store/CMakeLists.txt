# Header-only: ota_signing_pubkey.h (committable, public key only) and
# qemu_test_ca.h (QEMU-only, generated local test fixture, gitignored) are
# produced by keys/gen_fw_ota_keys.sh and
# firmware/test/qemu/scripts/gen-test-pki.sh before the first build.
idf_component_register(
    INCLUDE_DIRS "include"
)
