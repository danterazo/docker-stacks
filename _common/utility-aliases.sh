#!/bin/bash

alias dwatch='watch -d -n 1'
alias cff='clear && fastfetch'
alias sn='sudo nano'
alias sc='sudo cat'
alias rm-empty-dirs="sudo find . -type d -empty -print -delete"
alias ramdisk="mkdir -p /tmp/ramdisk && cd /tmp/ramdisk && ls -al"

alias dls='ls -Al'
alias lsa='ls --color=auto -al --group-directories-first'
alias ddu="du -B1G -sc * | numfmt --suffix=' GB' --grouping"
alias ddu2="du -B1M -sc * | numfmt --suffix=' MB' --grouping"
alias gcm="git commit -m"
