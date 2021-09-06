#!/usr/bin/env bash

# ? Maintained by nikolas.lucansky@gmail.com

checkDependency() {
    tools=(wget mkdir unzip lsb_release grep head uuidgen)
    for i in ${tools[@]}; do
        if [ ! $(command -v ${i}) ]; then
            echo "$i not detected"
            exit 1
        fi
    done
}

checkOS() {
    if [ $(lsb_release -a | grep "Ubuntu" -c) -gt 1 ]; then
        echo "### | Ubuntu detected! [OK]"
    else
        echo "Unsupported OS!"
        exit 1
    fi
}

getLatestVersion() {
    LATEST_VERSION=$(curl -s https://releases.hashicorp.com/terraform/ | grep -v "alpha\|beta\|rc" | grep terraform | head -1 | grep -Po '(?<=/)[0-9.]+')
    if [ -z ${LATEST_VERSION} ]; then
        echo -e "LATEST_VERSION is empty ! "
        exit 1
    fi

    if [ $(command -v terraform) ]; then
        echo "### | Local terraform detected $(terraform version)"
        if [[ "$(terraform version | grep -Po '[0.9].*')" == "${LATEST_VERSION}" ]]; then
            echo "### | Latest version is already installed!"
            exit 0
        fi
    fi
}

downloadTerraform() {
    UUID=$(uuidgen)
    mkdir -p /tmp/${UUID}/extracted || exit 1
    wget -P /tmp/${UUID} "https://releases.hashicorp.com/terraform/${LATEST_VERSION}/terraform_${LATEST_VERSION}_linux_amd64.zip"
    unzip "/tmp/${UUID}/terraform_${LATEST_VERSION}_linux_amd64.zip" -d /tmp/${UUID}/extracted
    cp /tmp/${UUID}/extracted/terraform /usr/local/bin

}

cleanup() {
    rm -rf /tmp/${UUID} || exit 1
    echo -e "### | CLEANUP [OK]"
}

# ? --- MAIN ---

if [[ $(/usr/bin/id -u) -ne 0 ]]; then
    echo "### | Not running as root"
    exit
fi

checkDependency
checkOS
getLatestVersion
downloadTerraform
cleanup
