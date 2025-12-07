# ------------------- Simple Shell (cleaned & fixed) -------------------
# This file preserves the original tokenization and parsing logic,
# then provides a clean, corrected implementation for process creation,
# pipelines, redirection, and background job control.

import os
import sys
import subprocess
import signal
import threading

# ------------------- "Built-in commandss"-------------------

def execute_builtin(cmd):
    """
    Executes built-in commands:
    cd, pwd, exit, help
    Returns True if command is built-in, else False.
    """
    if not cmd or not cmd.get("argv"):
        return False
    command_name = cmd["argv"][0]
    args = cmd["argv"][1:]

    # --------- "Change directory"--------- #
    if command_name == "cd":
        if len(args) == 0:
            ### no argument -> go to home
            try:
                os.chdir(os.path.expanduser("~"))
            except Exception as e:
                print(f"cd: error: {e}")
        else:
            target_dir = args[0]
            try:
                os.chdir(target_dir)
            except FileNotFoundError:
                print(f"cd: {target_dir}: No such file or directory")
            except PermissionError:
                print(f"cd: {target_dir}: Permission denied")
            except Exception as e:
                print(f"cd: error: {e}")
        return True

    # --------- "Print current working directory"--------- #
    elif command_name == "pwd":
        print(os.getcwd())
        return True

    # --------- "Exit the shell"--------- #
    elif command_name == "exit":
        exit_code = 0
        if len(args) > 0:
            try:
                exit_code = int(args[0])
            except ValueError:
                print(f"exit: {args[0]}: numeric argument required")
        sys.exit(exit_code)

    # --------- "Show built-in commands"--------- #
    elif command_name == "help":
        print("Simple Shell - Built-in Commands:")
        print("  cd [directory]    Change the current directory")
        print("  pwd               Print the current working directory")
        print("  exit [code]       Exit the shell with optional exit code")
        print("  help              Display this help message")
        print("  jobs              List background jobs")
        print("  fg <jobid>        Bring background job to foreground")
        return True
    ### Not a built-in command
    return False

# ------------------- "Tokenizerrr"------------------- #

def tokenize(line):
    """Convert input line into list of tokens."""
    tokens = []
    i = 0
    L = len(line)

    while i < L:
        ch = line[i]
        # --------- "skip spaces"--------- #
        if ch.isspace():
            i += 1
            continue
        # --------- "append redirection"--------- #
        if ch == '>' and i + 1 < L and line[i+1] == '>':
            tokens.append('>>')
            i += 2
            continue
        # --------- "single-char specials"--------- #
        if ch in ['|', '<', '>', '&']:
            tokens.append(ch)
            i += 1
            continue
        # --------- "quoted stringgg"--------- #
        if ch in ['"', "'"]:
            quote = ch
            i += 1
            buf = []
            while i < L and line[i] != quote:
                buf.append(line[i])
                i += 1
            if i < L:
                i += 1  ### skip closing quote
            tokens.append(''.join(buf))
            continue
        # --------- "normal token"--------- #
        buf = []
        while (
            i < L and
            not line[i].isspace() and
            line[i] not in ['|', '<', '>', '&', '"', "'"]
        ):
            buf.append(line[i])
            i += 1
        tokens.append(''.join(buf))
    return tokens

# ------------------- "Parserrr"------------------- #

def parse_tokens(tokens):
    """
    convert list of tokens into command dicts.
    Each command has:      - argv: list of words      - in: input redirection file      - out: output redirection file      - append: True if >>      - bg: True if background (&)
    """
    cmds = []
    cur = {"argv": [], "in": None, "out": None, "append": False, "bg": False}

    i = 0
    L = len(tokens)
    while i < L:
        t = tokens[i]

        if t == "|":
            cmds.append(cur)
            cur = {"argv": [], "in": None, "out": None, "append": False, "bg": False}
            i += 1
            continue

        elif t == "<":
            if i + 1 < L:
                cur["in"] = tokens[i + 1]
            i += 2
            continue

        elif t == ">":
            if i + 1 < L:
                cur["out"] = tokens[i + 1]
                cur["append"] = False
            i += 2
            continue

        elif t == ">>":
            if i + 1 < L:
                cur["out"] = tokens[i + 1]
                cur["append"] = True
            i += 2
            continue

        elif t == "&":
            cur["bg"] = True
            i += 1
            continue

        else:
            cur["argv"].append(t)
            i += 1

    if cur["argv"] or cur["in"] or cur["out"] or cur["bg"]:
        cmds.append(cur)

    return cmds


def parse_line(line):
    """shortcut to tokenize and parse a line"""
    return parse_tokens(tokenize(line))

# ------------------- Job & signal management -------------------

_jobs_lock = threading.Lock()
_jobs = {}  # jid -> {pids: [...], cmdline: str, status: str}
_next_job_id = 1


def _register_job(pids, cmdline, status="running"):
    global _next_job_id
    with _jobs_lock:
        jid = _next_job_id
        _next_job_id += 1
        _jobs[jid] = {"pids": pids, "cmdline": cmdline, "status": status}
    return jid


def _update_job_status(pid, exitcode=None):
    with _jobs_lock:
        for jid, info in _jobs.items():
            if pid in info.get("pids", []):
                info["status"] = f"done ({exitcode})" if exitcode is not None else "stopped"
                return jid
    return None


def _sigchld_handler(signum, frame):
    # Reap any child processes that have exited and update jobs table
    try:
        while True:
            pid, status = os.waitpid(-1, os.WNOHANG)
            if pid == 0:
                break
            exitcode = None
            if os.WIFEXITED(status):
                exitcode = os.WEXITSTATUS(status)
            jid = _update_job_status(pid, exitcode)
            if jid:
                print(f"[job {jid}] process {pid} exited with {exitcode}")
            try:
                sys.stdout.write("$ ")
                sys.stdout.flush()
            except Exception:
                pass
    except ChildProcessError:
        pass

# install SIGCHLD handler (POSIX systems)
try:
    signal.signal(signal.SIGCHLD, _sigchld_handler)
except Exception:
    # Not all platforms support SIGCHLD (e.g., some Windows builds).
    pass

# ------------------- Execution: pipelines, redirection, background -------------------

def _open_for_read(path):
    try:
        return open(path, 'rb')
    except Exception as e:
        print(f"redirection error (input): {e}")
        return None


def _open_for_write(path, append=False):
    mode = 'ab' if append else 'wb'
    try:
        return open(path, mode)
    except Exception as e:
        print(f"redirection error (output): {e}")
        return None


def run_pipeline(cmds):
    """Run parsed command dicts as a pipeline.
    Supports input/output redirection and background (& on last command).
    Returns (is_background, info) where info is exitcode (foreground) or jobid (background).
    """
    procs = []
    prev_proc = None
    in_file = None
    out_file = None

    try:
        for idx, cmd in enumerate(cmds):
            argv = cmd.get('argv', [])
            if not argv:
                continue

            stdin = None
            stdout = None

            # handle input redirection for first command
            if idx == 0 and cmd.get('in'):
                in_file = _open_for_read(cmd['in'])
                stdin = in_file
            elif prev_proc is not None:
                stdin = prev_proc.stdout

            # handle output redirection for last command
            if idx == len(cmds) - 1 and cmd.get('out'):
                out_file = _open_for_write(cmd['out'], append=bool(cmd.get('append')))
                stdout = out_file
            elif idx != len(cmds) - 1:
                stdout = subprocess.PIPE

            # launch process
            try:
                proc = subprocess.Popen(argv, stdin=stdin, stdout=stdout, stderr=subprocess.PIPE, close_fds=True)
            except FileNotFoundError:
                print(f"{argv[0]}: command not found")
                # cleanup started processes
                for p in procs:
                    try:
                        p.kill()
                    except Exception:
                        pass
                return False, None
            except Exception as e:
                print(f"failed to execute {argv}: {e}")
                for p in procs:
                    try:
                        p.kill()
                    except Exception:
                        pass
                return False, None

            procs.append(proc)

            # close previousproc stdout in parent to avoid hanging
            if prev_proc is not None and prev_proc.stdout:
                try:
                    prev_proc.stdout.close()
                except Exception:
                    pass
            prev_proc = proc

        if not procs:
            return False, None

        is_bg = cmds[-1].get('bg', False)
        pids = [p.pid for p in procs]
        cmdline = ' '.join(sum([c.get('argv', []) for c in cmds], []))

        if is_bg:
            jid = _register_job(pids, cmdline)
            print(f"[job {jid}] {pids[0]}")
            return True, jid
        else:
            # foreground: wait for last process and return its exit code
            rc = None
            try:
                rc = procs[-1].wait()
            except KeyboardInterrupt:
                # propagate Ctrl+C to children
                for p in procs:
                    try:
                        p.kill()
                    except Exception:
                        pass
            return False, rc

    finally:
        # close any redirection files opened by us
        try:
            if in_file and not in_file.closed:
                in_file.close()
        except Exception:
            pass
        try:
            if out_file and not out_file.closed:
                out_file.close()
        except Exception:
            pass

# ------------------- Extended built-ins: jobs, fg -------------------

def _builtin_jobs():
    with _jobs_lock:
        if not _jobs:
            print("No background jobs")
            return
        for jid, info in _jobs.items():
            pids = ','.join(str(p) for p in info.get('pids', []))
            print(f"[{jid}] {info.get('status')}	{pids}	{info.get('cmdline')}")


def _builtin_fg(cmd):
    if len(cmd.get('argv', [])) < 2:
        print("fg: job id required")
        return True
    try:
        jid = int(cmd['argv'][1])
    except ValueError:
        print("fg: numeric job id required")
        return True
    with _jobs_lock:
        job = _jobs.get(jid)
        if not job:
            print(f"fg: job {jid} not found")
            return True
        pids = job.get('pids', [])
        print(f"Bringing job {jid} to foreground: {job.get('cmdline')}")
    # wait for job pids
    for pid in pids:
        try:
            os.waitpid(pid, 0)
        except Exception:
            pass
    with _jobs_lock:
        job['status'] = 'done'
    return True

# hook into execute_builtin - wrap original functionality
_original_execute_builtin = execute_builtin

def execute_builtin(cmd):
    # first check the extended built-ins
    if not cmd or not cmd.get('argv'):
        return False
    name = cmd['argv'][0]
    if name == 'jobs':
        _builtin_jobs()
        return True
    if name == 'fg':
        return _builtin_fg(cmd)
    # fallback to original builtins
    return _original_execute_builtin(cmd)

# ------------------- Main loop (clean, uses parse_line) -------------------

def main():
    while True:
        try:
            user_input = input('$ ')
        except EOFError:
            print()
            print('exit')
            break
        except KeyboardInterrupt:
            print()
            continue

        line = user_input.strip()
        if not line:
            continue

        try:
            cmds = parse_line(line)
            if not cmds:
                continue

            # check if it's a built-in (only check first command)
            if cmds and execute_builtin(cmds[0]):
                continue

            # execute pipeline / external commands
            bg, info = run_pipeline(cmds)
            # bg True -> info is job id; bg False -> info is exit code

        except Exception as e:
            print(f"Error: {e}")


if __name__ == '__main__':
    main()
