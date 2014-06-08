#!/usr/bin/env bash

# tmuxp completion
# See: http://www.debian-administration.org/articles/317 for how to write more.
# Usage: Put "source tmuxp_completion.sh" into your .bashrc
# Based upon the example at http://paste-it.appspot.com/Pj4mLycDE

_tmuxp_cmds=" \
load \
freeze"

function _tmux_complete_session() {
    local IFS=$'\n'
    local cur="${1}"
    COMPREPLY=( ${COMPREPLY[@]:-} $(compgen -W "$(tmux -q list-sessions 2>/dev/null | cut -f 1 -d ':')" -- "${cur}") )
}

function _tmuxp_files() {
    local IFS=$'\n'
    local cur="${1}"
    COMPREPLY=( ${COMPREPLY[@]:-} $(compgen -W "$(ls ~/.tmuxp 2>/dev/null)" -- "${cur}") )
}
_tmuxp()
{
  local cur prev
  local i cmd cmd_index
  COMPREPLY=()
  cur="${COMP_WORDS[COMP_CWORD]}"
  prev="${COMP_WORDS[COMP_CWORD-1]}"

    local skip_next=0
    for ((i=1; $i<=$COMP_CWORD; i++)); do
        if [[ ${COMP_WORDS[i]} != -* ]]; then
            cmd="${COMP_WORDS[i]}"
            cmd_index=${i}
            break
        fi
    done

    if [[ $COMP_CWORD -le $cmd_index ]]; then
        # The user has not specified a command yet
        COMPREPLY=( ${COMPREPLY[@]:-} $(compgen -W "${_tmuxp_cmds}" -- "${cur}") )
    else
        case ${cmd} in
	    freeze) _tmux_complete_session "${cur}" ;;
	    load) _tmuxp_files "${cur}" ;;
	esac
    fi
   return 0
}
complete -F _tmuxp tmuxp
