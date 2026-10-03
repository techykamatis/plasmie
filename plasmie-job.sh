#!/bin/bash
# plasmie-job.sh <minutes> <script> [args…]: run a background job with a hard time limit.
# launchd has no maximum runtime, and a job wedged on the network or the model would
# otherwise sit forever (goal item 7: no hangs). The job runs in its own process group;
# past the limit the whole group gets TERM, then KILL 10 s later, and plasmie-job exits 124
# (visible as the job's last exit status in launchctl and Copy diagnostics).
set -u
mins="${1:?usage: plasmie-job.sh <minutes> <script> [args]}"; shift
script="${1:?usage: plasmie-job.sh <minutes> <script> [args]}"; shift
here="$(cd "$(dirname "$0")" && pwd)"
exec /usr/bin/perl -e '
  my $secs = shift;
  my $pid = fork();
  die "fork: $!" unless defined $pid;
  if ($pid == 0) { setpgrp(0, 0); exec @ARGV; exit 127 }
  local $SIG{ALRM} = sub {
    kill "TERM", -$pid; sleep($ENV{PLASMIE_JOB_GRACE} // 10); kill "KILL", -$pid;
    print STDERR scalar(localtime) . " plasmie-job: $ARGV[1] over its time limit; stopped\n";
    exit 124;
  };
  alarm $secs;
  waitpid($pid, 0);
  alarm 0;
  exit($? >> 8);
' "${PLASMIE_JOB_SECS:-$((mins * 60))}" /bin/bash "$here/$script" "$@"   # PLASMIE_JOB_SECS: tests
