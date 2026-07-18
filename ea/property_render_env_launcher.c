#include <stddef.h>
#include <string.h>
#include <unistd.h>

extern char **environ;

static int is_forbidden_loader_entry(const char *entry)
{
    const char *separator = strchr(entry, '=');
    const size_t name_length =
        separator == NULL ? strlen(entry) : (size_t)(separator - entry);
    static const char glibc_tunables[] = "GLIBC_TUNABLES";
    static const char gconv_path[] = "GCONV_PATH";

    if (name_length >= 3U && memcmp(entry, "LD_", 3U) == 0) {
        return 1;
    }
    if (name_length == sizeof(glibc_tunables) - 1U &&
        memcmp(entry, glibc_tunables, sizeof(glibc_tunables) - 1U) == 0) {
        return 1;
    }
    return name_length == sizeof(gconv_path) - 1U &&
        memcmp(entry, gconv_path, sizeof(gconv_path) - 1U) == 0;
}

static void sanitize_loader_environment(void)
{
    char **source = environ;
    char **destination = environ;

    if (source == NULL) {
        return;
    }
    while (*source != NULL) {
        if (!is_forbidden_loader_entry(*source)) {
            *destination = *source;
            ++destination;
        }
        ++source;
    }
    *destination = NULL;
}

static void fail_closed(void)
{
    static const char message[] = "property-render-launcher: failed\n";
    const ssize_t ignored = write(STDERR_FILENO, message, sizeof(message) - 1U);

    (void)ignored;
    _exit(126);
}

int main(int argc, char **argv)
{
    if (argc < 2 || argv[1] == NULL || argv[1][0] == '\0') {
        fail_closed();
    }

    sanitize_loader_environment();
    execv(argv[1], &argv[1]);
    fail_closed();
}
