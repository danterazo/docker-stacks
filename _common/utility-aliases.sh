#!/bin/bash
# canonical shared utilities. docker LXCs receive a generated copy through Make.

: 'General Utilities'
alias dwatch="watch -d -n 1"
alias cff="clear && fastfetch"
upgrade() {
	sudo apt-get update && sudo apt-get dist-upgrade -y && sudo apt-get clean && sudo apt-get autoremove -y --purge
}
alias sn="sudo nano"
alias sc="sudo cat"
alias rm-empty-dirs="sudo find . -type d -empty -print -delete"
alias ramdisk="mkdir -p /tmp/ramdisk && cd /tmp/ramdisk && ls -al"

: 'Directory Listings & Disk Usage'
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

: 'Git'
alias gcm="git commit -m"
