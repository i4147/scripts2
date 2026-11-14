if [[ $- == *i* ]] && [ -z "$UNDER_SCRIPT" ]; then
    LOG_DIR="$HOME/tmp/log"
    mkdir -p "$LOG_DIR"
    LOG_FILE="$LOG_DIR/$(LC_TIME=C date +%a%d%b%H%M | tr '[:lower:]' '[:upper:]').log"
    export UNDER_SCRIPT=1
    exec script -q -f "$LOG_FILE"
fi


setopt NULLGLOB
#setopt HIST_IGNORE_ALL_DUPS
bindkey -e


#zstyle ':zim:git' aliases-prefix 'g'
#zstyle ':zim:input' double-dot-expand yes
export LANG=en_US.UTF-8
setopt autocd                 # Type a directory name to cd straight into it
setopt correct                # Command spelling correction
setopt correctall             # Argument spelling correction
setopt extendedglob           # Advanced globbing (^, ~, #)
setopt kshglob                # Bash/Ksh pattern expansions: @(...), !(...)

#setopt appendhistory          # Append to history file instead of overwriting
#setopt incappendhistory       # Write history lines immediately to file
#setopt hist_ignore_dups       # Ignore consecutive duplicate entries
#setopt hist_ignore_all_dups   # Remove old occurrences when a duplicate is added
#setopt hist_save_no_dups      # Do not write duplicate lines to history file
#setopt hist_find_no_dups      # Filter duplicates out during history lookups

#setopt prompt_subst

typeset -a PATH_DIRS
PATH_DIRS=(
    "$HOME/.local/bin"
    "$HOME/bin"
    "$HOME/bashbin"
    "$HOME/.cargo/bin"
    "$HOME/.npm-global/bin"
    "$PREFIX/bin"
    "$HOME/.local/share/nvim/mason/bin"
    "/system/bin"
)
NEW_PATH=""
add_path_dir() {
    local dir="$1"
    [[ -n "$dir" ]] || return 0
    case ":$NEW_PATH:" in
        *":$dir:"*) return 0 ;;
    esac
    NEW_PATH="${NEW_PATH:+$NEW_PATH:}$dir"
}
for dir in "${PATH_DIRS[@]}"; do
    [[ -d "$dir" ]] && add_path_dir "$dir"
done
IFS=':' read -r -A OLD_PATH <<< "$PATH"
for dir in "${OLD_PATH[@]}"; do
    add_path_dir "$dir"
done
export PATH="$NEW_PATH"


# precmd() {    printf '\e[3 q' }

# _set_cursor_shape() { printf '\e[5 q'  }

#add-zsh-hook precmd _set_cursor_shape


virtualenv_prompt_info() {
  [[ -n "$VIRTUAL_ENV" ]] || return
  print -n "%F{cyan}[${VIRTUAL_ENV:t}]%f "
}
# git branch (+ '*' when dirty), e.g. [main*]
git_prompt_info() {
  emulate -L zsh
  local ref dirty
  ref=$(command git symbolic-ref --short HEAD 2>/dev/null) \
    || ref=$(command git rev-parse --short HEAD 2>/dev/null) \
    || return
  [[ -n $(command git status --porcelain 2>/dev/null) ]] && dirty='*'
  print -n "%F{yellow}[${ref}${dirty}]%f "
}
rgb() { print -n "%F{#$(printf '%02x%02x%02x' $1 $2 $3)}" }

FG_GRAY=$(rgb 168 158 146)
FG_GREEN=$(rgb 8 225 190)
FG_CYAN=$(rgb 196 145 251)
FG_YELLOW=$(rgb 175 228 147)

RESET='%f'

PROMPT="${FG_GRAY}[${RESET}${FG_GREEN}%1~${RESET}${FG_GRAY}]${RESET}"
#PROMPT+='$(virtualenv_prompt_info)'
#PROMPT+='${YELLOW}$(git_prompt_info)'
PROMPT+='
$ '
#export PROMPT

ZSH_THEME_VIRTUALENV_PREFIX=" %F{yellow}("
ZSH_THEME_VIRTUALENV_SUFFIX=")%f"
ZSH_THEME_GIT_PROMPT_PREFIX=" %F{magenta}("
ZSH_THEME_GIT_PROMPT_SUFFIX=")%f"
ZSH_THEME_GIT_PROMPT_DIRTY=" %F{yellow9o}✗%f"
ZSH_THEME_GIT_PROMPT_CLEAN=" %F{green}✓%f"

[[ -f ~/.ls_colors ]] && source ~/.ls_colors

