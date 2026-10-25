#!/bin/bash
# canonical shared utilities. docker LXCs receive a generated copy through Make.

alias dwatch="watch -d -n 1"
alias cff="clear && fastfetch"
unalias upgrade 2>/dev/null || true
upgrade() {
	sudo apt update && sudo apt dist-upgrade -y && sudo apt clean && sudo apt autoremove -y --purge
}
alias sn="sudo nano"
alias sc="sudo cat"
alias rm-empty-dirs="sudo find . -type d -empty -print -delete"
alias ramdisk="mkdir -p /tmp/ramdisk && cd /tmp/ramdisk && ls -al"

alias ls="ls --color=auto"
alias grep="grep --color=auto"
alias fgrep="fgrep --color=auto"
alias egrep="egrep --color=auto"
alias dls="ls -Al"
alias ll="ls -alF"
alias la="ls -A"
alias l="ls -CF"
alias lsa="ls --color=auto -al --group-directories-first"
alias ddu="du -B1G -sc * | numfmt --suffix=' GB' --grouping"
alias ddu2="du -B1M -sc * | numfmt --suffix=' MB' --grouping"

alias gcm="git commit -m"
