#!/bin/sh
set -e

# Substitutes the journal names into the template and runs logrotate on a
# schedule.
#
# The names come from the same three variables the application chooses them
# by. Without this step the configuration named the files literally, and a
# deployment that set its own LOG_FILENAME was left without rotation in
# silence: missingok swallows the missing file, the rotator returns zero,
# and the journal grows until the disk ends.
#
# The defaults are BaseConfig's. Written down a second time, yes, but the
# alternative is worse: without them an unset variable turns the path into
# `/logs/.log`, and rotation again quietly does nothing.
export LOG_FILENAME="${LOG_FILENAME:-application}"
export ERROR_LOG_FILENAME="${ERROR_LOG_FILENAME:-error}"
export AUDIT_LOG_FILENAME="${AUDIT_LOG_FILENAME:-audit}"

# A journal name is a name, not a path. The application checks these three
# settings at startup and refuses to come up with a bad one, but the rotator
# is a separate container: it would come up and rotate `/logs/../anything`
# while the operator works out why the application did not. The check admits
# and refuses exactly what `JOURNAL_NAME` in configs/app/base.py does, and
# both halves of that had to be repaired: the pattern there matched with
# `re.match` against `^...$`, which accepts a trailing newline -- the shape a
# value read out of a file or a Secret arrives in -- so the application
# started on `LOG_FILENAME=application\n` and this container exited 1 on the
# same value. The second branch below is the other half: `.*` refused only a
# leading dot, so `_app` and `-app` were rotated here and refused there.
for name in "${LOG_FILENAME}" "${ERROR_LOG_FILENAME}" "${AUDIT_LOG_FILENAME}"; do
    case "${name}" in
        *[!A-Za-z0-9._-]* | [!A-Za-z0-9]* | "")
            echo "refusing to rotate: '${name}' is not a journal name" >&2
            exit 1
            ;;
    esac
done

# These three and no others: envsubst with no list substitutes every
# `${...}` it comes across, and a logrotate configuration should carry no
# such construct at all -- if one appears, let it stand as written.
envsubst '${LOG_FILENAME} ${ERROR_LOG_FILENAME} ${AUDIT_LOG_FILENAME}' \
    < /etc/logrotate.d/link_shortener.template \
    > /etc/logrotate.d/link_shortener

echo "logrotate will follow: ${LOG_FILENAME}.log, ${ERROR_LOG_FILENAME}.log, ${AUDIT_LOG_FILENAME}.log"

# `render` -- substitute and exit, no loop. It exists for the test that
# asks the real logrotate whether it accepts what we ship: the question has
# to be about the finished configuration, and this script is what finishes
# it. A test repeating the substitution itself would be checking its own
# copy.
if [ "$1" = "render" ]; then
    exit 0
fi

# The interval is a whole number of seconds, checked for the same reason as
# the names: `sleep abc` fails and returns at once, so the loop stops being
# a schedule and becomes a busy loop -- logrotate is called without pause
# and `docker logs` fills with refusals at the speed of the disk. A typo in
# a variable, nothing more.
case "${LOG_ROTATE_INTERVAL}" in
    "" | *[!0-9]* | 0)
        echo "refusing to run: LOG_ROTATE_INTERVAL='${LOG_ROTATE_INTERVAL}'" \
             "is not a positive whole number of seconds" >&2
        exit 1
        ;;
esac

# A loop for the schedule, not cron: see Dockerfile.logrotate.
#
# A failure is not swallowed: logrotate returns a non-zero code when it
# could not move a file aside -- most often over permissions on the
# directory -- and that has to be learnt from `docker logs` rather than
# from silence.
while true; do
    logrotate --state /logs/.logrotate.state /etc/logrotate.d/link_shortener \
        || echo 'logrotate failed, see the message above' >&2
    sleep "${LOG_ROTATE_INTERVAL}"
done
