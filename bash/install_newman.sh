#!/usr/bin/env bash

# ? Maintained by nikolas.lucansky@gmail.com

if [[ $(/usr/bin/id -u) -ne 0 ]]; then
    echo "### | Not running as root"
    exit
fi

checkOS() {
    if [ $(lsb_release -a | grep "Ubuntu" -c) -gt 1 ]; then
        echo "### | Ubuntu detected! [OK]"
    else
        echo "Unsupported OS!"
        exit 1
    fi
}

checkDependency() {
    tools=(lsb_release grep head)
    for i in "${tools[@]}"; do
        if [ ! $(command -v ${i}) ]; then
            echo "$i not detected"
            exit 1
        fi
    done
}

# ! --- MAIN ---
checkOS
checkDependency

if [ ! "$(command -v newman)" ]; then
    if [ ! "$(command -v npm)" ]; then
        apt-get install -y npm || exit
    else
        echo -e "### | npm is already installed"
    fi
    npm install -g newman || exit
else
    echo "### | newman is already installed"
fi
