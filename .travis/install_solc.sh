#!/bin/bash
#
# Install solc 
#

set -e
set -u

mkdir -p $HOME/solc-versions/solc-$SOLC_VERSION
cd $HOME/solc-versions/solc-$SOLC_VERSION

if [ ! -f solc ]
then
    git clone --recurse-submodules --branch v$SOLC_VERSION --depth 50 https://github.com/ethereum/solidity.git
    ./solidity/scripts/install_deps.sh
    wget https://github.com/ethereum/solidity/releases/download/v$SOLC_VERSION/solidity-ubuntu-trusty.zip
    unzip solidity-ubuntu-trusty.zip
    echo "Solidity installed at $HOME/solc-versions/solc-$SOLC_VERSION/solc"
    tree $HOME/solc-versions/solc-$SOLC_VERSION
else
    ./solidity/scripts/install_deps.sh
fi

if [ -f $HOME/.bin/solc ]
then
    rm $HOME/.bin/solc
fi

ln -s $HOME/solc-versions/solc-$SOLC_VERSION/solc $HOME/.bin/solc
# Check path is correctly set up and echo version
cd
echo $PATH
ls -al $HOME/.bin
ls -al $(readlink -f $HOME/.bin/solc)
solc --version
