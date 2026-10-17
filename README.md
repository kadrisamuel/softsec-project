# tatou
A web platform for pdf watermarking. This project is intended for pedagogical use, and contain security vulnerabilities. Do not deploy on an open network.

## Instructions

The following instructions are meant for a bash terminal on a Linux machine. If you are using something else, you will need to adapt them.

### Run python unit tests

```bash
cd tatou/server

# Create a python virtual environement
python3 -m venv .venv

# Activate your virtual environement
. .venv/bin/activate

# Install the necessary dependencies
python -m pip install -r requirements-dev.txt

# Run the unit tests
python -m pytest
```

### Run mutmut mutation testing

```bash
cd tatou/server

# Create a python virtual environement
python3 -m venv .venv

# Activate your virtual environement
. .venv/bin/activate

# Install the necessary dependencies
python -m pip install -r requirements-dev.txt

# Run mutmut
mutmut run

# Browse mutmut results
mutmut browse
```

### Deploy

Before deploying the service on a local machine, place the group PDF and export of the GPG private key in the root of the project as `Group_02.pdf` and `private.key`, respectively.

From the root of the repository:

```bash
# Create a file to set environement variables like passwords.
cp sample.env .env

# Edit .env and set unique values

# Rebuild the docker image and deploy the containers
docker compose up --build -d

# Monitor logs in realtime
docker compose logs -f

# Test if the API is up
http -v :5000/healthz

# Open your browser at 127.0.0.1:5000 to check if the website is up.
```

### VM configuration

This repository assumes that a properly configured VM exists, which will be used as the deployment target for the following step.

The configuration of this VM can be done to the user's liking, but we still provide the basic configuration we applied to our VM in `vm_config`. This directory includes:
- `sshd_config` - restrictive sshd config only allowing key-based SSH access for the `softsec` user. We had to enable IP forwarding later to interact with the other groups' services
- `ufw.txt` - a list of commands applied to configure UFW. We only allow access to SSH and our service port.

### VM Deploy

Prerequisites:
- Working ssh connection to VM
- fully populated `.env` file
- db schema in `/deployment/db/` on VM
- secret files in `/deployment/secrets/` on VM

The required secret files are:
- private.key: Private GPG key for RMAP
- Group_02.pdf: Group PDF for RMAP

Make sure to restrict the access rights to those files to their owner softsec in read-only mode.

From the root of the repository:

```bash
# Set up docker context
docker context create softsec-vm --docker "host=ssh://softsec@softsec-group-02.dsv.local.su.se"

# Apply deploy patch to docker compose
git apply vm-deploy.patch

# Build and deploy container on VM
docker compose up --context softsec-vm --build -d
```

### Updating dependencies
In addition to our dependency definitions inside `pyproject.toml`, we also keep track of all transitive dependencies using generated `requirements.txt` and `requirements-dev.txt` files.

To update python dependencies, follow the following steps:
1. Add, change, or remove dependencies in `pyproject.toml`. Make sure to specify the exact version number for the dependency.
2. Move to the server directory
3. Run `pip-compile --strip-extras pyproject.toml` to create updated `requirements.txt`
4. Run `pip-compile --extra dev -o requirements-dev.txt pyproject.toml` to create updated `requirements-dev.txt`
5. Run `pip install -r requirements(-dev).txt` to install the most recent (dev-)dependencies
6. Move to the root of the repository
7. Run `scripts/sbom-generator.sh`
8. Commit all altered files

When updating the db or base image in the docker build process, specify the exact version with the respective sha256 hash.
