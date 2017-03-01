#!/usr/bin/env bash

set -e

fail() {
    if [[ $- == *i* ]]; then
       red=`tput setaf 1`
       reset=`tput sgr0`

       echo "${red}==> ${@}${reset}"
    fi
    exit 1
}

info() {
    if [[ $- == *i* ]]; then
        blue=`tput setaf 4`
        reset=`tput sgr0`

        echo "${blue}${@}${reset}"
    fi
}

success() {
    if [[ $- == *i* ]]; then
        green=`tput setaf 2`
        reset=`tput sgr0`
        echo "${green}${@}${reset}"
    fi

}

warn() {
    if [[ $- == *i* ]]; then
        yellow=`tput setaf 3`
        reset=`tput sgr0`

        echo "${yellow}${@}${reset}"
    fi
}

[ -z "${SOLC_URL}" ] && fail 'missing SOLC_URL'
[ -z "${SOLC_VERSION}" ] && fail 'missing SOLC_VERSION'

if [ ! -x $HOME/.bin/solc-${SOLC_VERSION} ]; then
    mkdir -p $HOME/.bin

    curl -L $SOLC_URL > $HOME/.bin/solc-${SOLC_VERSION}
    chmod 775 $HOME/.bin/solc-${SOLC_VERSION}

    success "solc ${SOLC_VERSION} installed"
else
    info 'using cached solc'
fi

# always recreate the symlink since we dont know if it's pointing to a different
# version
[ -h $HOME/.bin/solc ] && unlink $HOME/.bin/solc
ln -s $HOME/.bin/solc-${SOLC_VERSION} $HOME/.bin/solc
