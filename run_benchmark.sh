#!/usr/bin/env bash

# USAGE:
#   ./run_benchmark.sh <server_host> <client_host> <ilab_username> <password_file>
#
# EXAMPLE:
#   ./run_benchmark.sh grep.cs.rutgers.edu kill.cs.rutgers.edu mdc265 ~/.ilab_pass

set -uo pipefail

SERVER_HOST="${1:?Usage: $0 <server_host> <client_host> <username> <password_file>}"
CLIENT_HOST="${2:?}"
USERNAME="${3:?}"
PASSWORD_FILE="${4:?}"

REMOTE_DIR="/common/home/${USERNAME}/tcp_udp_benchmark"
LOCAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PAYLOAD_SIZES=(64 512 1024 4096 8192)
CLIENT_COUNTS=(1 10 100 1000)
REQUESTS=100
TCP_PORT=5101
UDP_PORT=5102

log() { echo "[$(date '+%H:%M:%S')] $*"; }

# Run a command on a remote host via expect
# The command is passed as a single string — no shell splitting issues
ssh_run() {
    local host="$1"
    local cmd="$2"
    expect << EOFEXPECT
set f [open "$PASSWORD_FILE" r]
set pass [string trim [read \$f]]
close \$f
spawn ssh -o StrictHostKeyChecking=no ${USERNAME}@${host} {$cmd}
expect "Password: "
send "\$pass\r"
expect eof
EOFEXPECT
}

# Copy a single file to remote host
scp_to() {
    local host="$1"
    local local_path="$2"
    local remote_path="$3"
    expect << EOFEXPECT
set f [open "$PASSWORD_FILE" r]
set pass [string trim [read \$f]]
close \$f
spawn scp -o StrictHostKeyChecking=no $local_path ${USERNAME}@${host}:${remote_path}
expect "Password: "
send "\$pass\r"
expect eof
EOFEXPECT
}

# Copy remote path back to local
scp_from() {
    local host="$1"
    local remote_path="$2"
    local local_path="$3"
    expect << EOFEXPECT
set f [open "$PASSWORD_FILE" r]
set pass [string trim [read \$f]]
close \$f
spawn scp -r -o StrictHostKeyChecking=no ${USERNAME}@${host}:${remote_path} $local_path
expect "Password: "
send "\$pass\r"
expect eof
EOFEXPECT
}

log "================================================================"
log "STEP 1: Copying files to server ($SERVER_HOST) and client ($CLIENT_HOST)"
log "================================================================"

ssh_run "$SERVER_HOST" "mkdir -p ${REMOTE_DIR}/results ${REMOTE_DIR}/plots"
ssh_run "$CLIENT_HOST" "mkdir -p ${REMOTE_DIR}/results ${REMOTE_DIR}/plots"

for f in client.py server.py run_experiments.py; do
    log "  Copying $f to $SERVER_HOST..."
    scp_to "$SERVER_HOST" "${LOCAL_DIR}/$f" "${REMOTE_DIR}/$f"
    log "  Copying $f to $CLIENT_HOST..."
    scp_to "$CLIENT_HOST" "${LOCAL_DIR}/$f" "${REMOTE_DIR}/$f"
done

log "  Verifying on $SERVER_HOST..."
ssh_run "$SERVER_HOST" "ls ${REMOTE_DIR}/"
log "  Verifying on $CLIENT_HOST..."
ssh_run "$CLIENT_HOST" "ls ${REMOTE_DIR}/"

log "Files synced."

log ""
log "================================================================"
log "STEP 2: Running experiments"
log "================================================================"

for PROTO in tcp udp; do

    if [[ "$PROTO" == "tcp" ]]; then
        PORT=$TCP_PORT
    else
        PORT=$UDP_PORT
    fi

    PROTO_UPPER=$(echo "$PROTO" | tr '[:lower:]' '[:upper:]')

    for CLIENTS in "${CLIENT_COUNTS[@]}"; do
        for PAYLOAD in "${PAYLOAD_SIZES[@]}"; do

            CLIENT_LOG="${REMOTE_DIR}/results/client_${PROTO}_p${PAYLOAD}_c${CLIENTS}.csv"
            SERVER_LOG="${REMOTE_DIR}/results/server_${PROTO}_p${PAYLOAD}_c${CLIENTS}.jsonl"

            log ""
            log "--- ${PROTO_UPPER}  payload=${PAYLOAD}B  clients=${CLIENTS}  requests=${REQUESTS} ---"

            # Start server in background — nohup keeps it alive after SSH exits
            ssh_run "$SERVER_HOST" "cd ${REMOTE_DIR} && nohup python3 server.py --proto ${PROTO} --bind 0.0.0.0 --port ${PORT} --payload-bytes ${PAYLOAD} --requests ${REQUESTS} --clients ${CLIENTS} --log ${SERVER_LOG} > /tmp/srv_${PROTO}_${PAYLOAD}_${CLIENTS}.log 2>&1 &"

            sleep 1   # give server time to bind

            # Run client — blocks until done
            ssh_run "$CLIENT_HOST" "cd ${REMOTE_DIR} && python3 client.py --proto ${PROTO} --host ${SERVER_HOST} --port ${PORT} --payload-bytes ${PAYLOAD} --requests ${REQUESTS} --clients ${CLIENTS} --log ${CLIENT_LOG}"

            sleep 1   # let OS reclaim sockets before next run

        done
    done
done

log ""
log "All experiments complete."


log ""
log "================================================================"
log "STEP 3: Generating plots on $CLIENT_HOST"
log "================================================================"

ssh_run "$CLIENT_HOST" "cd ${REMOTE_DIR} && python3 run_experiments.py --results-dir ${REMOTE_DIR}/results" \
    || log "WARN: run_experiments.py not found — skipping plots"


log ""
log "================================================================"
log "STEP 4: Downloading results/ and plots/ to local machine"
log "================================================================"

mkdir -p "${LOCAL_DIR}/results" "${LOCAL_DIR}/plots"
scp_from "$CLIENT_HOST" "${REMOTE_DIR}/results" "${LOCAL_DIR}/"
scp_from "$CLIENT_HOST" "${REMOTE_DIR}/plots"   "${LOCAL_DIR}/" || true

log ""
log "================================================================"
log "Done!  Results in: ${LOCAL_DIR}/results/"
log "Plots  in:         ${LOCAL_DIR}/plots/"
log "================================================================"


