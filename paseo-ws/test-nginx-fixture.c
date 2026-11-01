/* Native fixture: real executable identity and nginx-compatible master title. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <fcntl.h>
static char pidfile[4096];
static int events;
static void handle(int sig) {
    if (sig == SIGHUP) { write(events, "reload\n", 7); return; }
    write(events, "quit\n", 5);
    unlink(pidfile);
    _exit(0);
}
int main(int argc, char **argv) {
    if (fcntl(9, F_GETFD) != -1) return 98; /* The service lock must stay in the launcher. */
    const char *root = getenv("PASEO_TEST_ROOT");
    char file[4096];
    snprintf(pidfile, sizeof(pidfile), "%s/data/nginx/nginx.pid", root);
    snprintf(file, sizeof(file), "%s/signals", root);
    events = open(file, O_WRONLY|O_CREAT|O_APPEND, 0600);
    if (strncmp(argv[0], "nginx: master process ", sizeof("nginx: master process ") - 1) == 0) {
        signal(SIGHUP, handle); signal(SIGQUIT, handle);
        FILE *pid = fopen(pidfile, "w"); fprintf(pid, "%d\n", getpid()); fclose(pid);
        for (;;) pause();
    }
    snprintf(file, sizeof(file), "%s/calls", root);
    FILE *calls = fopen(file, "a");
    fputs("{\"command\":\"nginx\",\"args\":[", calls);
    for (int i=1; i<argc; i++) fprintf(calls, "%s\"%s\"", i==1 ? "" : ",", argv[i]);
    fputs("]}\n", calls); fclose(calls);
    for (int i=1; i<argc; i++) if (!strcmp(argv[i], "-t")) {
        snprintf(file, sizeof(file), "%s/reject-config", root);
        return access(file, F_OK) == 0 ? 1 : 0;
    }
    char title[16384] = "nginx: master process ";
    for (int i=0; i<argc; i++) { if (i) strcat(title, " "); strcat(title, argv[i]); }
    pid_t child = fork();
    if (child < 0) return 2;
    if (child == 0) {
        setsid();
        int null = open("/dev/null", O_RDWR);
        dup2(null, 0); dup2(null, 1); dup2(null, 2);
        char *args[] = {title, NULL}; execv(argv[0], args); _exit(3);
    }
    for (int i=0; i<500; i++) { if (access(pidfile, F_OK)==0) return 0; usleep(1000); }
    return 4;
}
