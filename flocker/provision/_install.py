# Copyright Hybrid Logic Ltd.  See LICENSE file for details.
# -*- test-case-name: flocker.provision.test.test_install -*-

"""
Install flocker on a remote node.
"""

from pipes import quote as shell_quote
import posixpath
from textwrap import dedent
from urlparse import urljoin
from characteristic import attributes

from ._common import PackageSource

ZFS_REPO = ("https://s3.amazonaws.com/archive.zfsonlinux.org/"
            "fedora/zfs-release$(rpm -E %dist).noarch.rpm")
CLUSTERHQ_REPO = ("https://storage.googleapis.com/archive.clusterhq.com/"
                  "fedora/clusterhq-release$(rpm -E %dist).noarch.rpm")


@attributes(["command"])
class Run(object):
    """
    Run a shell command on a remote host.

    :param bytes command: The command to run.
    """
    @classmethod
    def from_args(cls, command_args):
        return cls(command=" ".join(map(shell_quote, command_args)))


@attributes(["content", "path"])
class Put(object):
    """
    Create a file with the given content on a remote host.

    :param bytes content: The desired contests.
    :param bytes path: The remote path to create.
    """


def run_with_fabric(username, address, commands):
    """
    Run a series of commands on a remote host.

    :param bytes username: User to connect as.
    :param bytes address: Address to connect to
    :param list commands: List of commands to run.
    """
    from fabric.api import settings, run, put
    from fabric.network import disconnect_all
    from StringIO import StringIO

    handlers = {
        Run: lambda e: run(e.command),
        Put: lambda e: put(StringIO(e.content), e.path),
    }

    host_string = "%s@%s" % (username, address)
    with settings(
            connection_attempts=24,
            timeout=5,
            pty=False,
            host_string=host_string):

        for command in commands:
            handlers[type(command)](command)
    disconnect_all()


def task_install_kernel():
    """
    Install development headers corresponding to running kernel.

    This is so we can compile zfs.
    """
    return [Run(command="""
UNAME_R=$(uname -r)
PV=${UNAME_R%.*}
KV=${PV%%-*}
SV=${PV##*-}
ARCH=$(uname -m)
yum install -y https://kojipkgs.fedoraproject.org/packages/kernel/\
${KV}/${SV}/${ARCH}/kernel-devel-${UNAME_R}.rpm
""")]


def task_enable_docker():
    """
    Start docker and configure it to start automatically.
    """
    return [
        Run(command="systemctl enable docker.service"),
        Run(command="systemctl start docker.service"),
    ]


def task_disable_firewall():
    """
    Disable the firewall.
    """
    rule = ['--add-rule', 'ipv4', 'filter', 'FORWARD', '0', '-j', 'ACCEPT']
    return [
        Run.from_args(['firewall-cmd', '--permanent', '--direct'] + rule),
        Run.from_args(['firewall-cmd', '--direct'] + rule),
    ]


def task_create_flocker_pool_file():
    """
    Create a file-back zfs pool for flocker.
    """
    return [
        Run(command='mkdir -p /var/opt/flocker'),
        Run(command='truncate --size 10G /var/opt/flocker/pool-vdev'),
        Run(command='zpool create flocker /var/opt/flocker/pool-vdev'),
    ]


def task_install_flocker(package_source=PackageSource(),
                         distribution=None):
    """
    Install flocker.

    :param bytes distribution: The distribution the node is running.
    :param PackageSource package_source: The source from which to install the
        package.
    """
    commands = [
        Run(command="yum install -y " + ZFS_REPO),
        Run(command="yum install -y " + CLUSTERHQ_REPO)
    ]

    if package_source.branch:
        result_path = posixpath.join(
            '/results/omnibus/', package_source.branch, distribution)
        base_url = urljoin(package_source.build_server, result_path)
        repo = dedent(b"""\
            [clusterhq-build]
            name=clusterhq-build
            baseurl=%s
            gpgcheck=0
            enabled=0
            """) % (base_url,)
        commands.append(Put(content=repo,
                            path='/etc/yum.repos.d/clusterhq-build.repo'))
        branch_opt = ['--enablerepo=clusterhq-build']
    else:
        branch_opt = []

    if package_source.os_version:
        package = 'clusterhq-flocker-node-%s' % (package_source.os_version,)
    else:
        package = 'clusterhq-flocker-node'

    commands.append(Run.from_args(
        ["yum", "install"] + branch_opt + ["-y", package]))

    return commands


def provision(node, username, distribution, package_source):
    """
    Provison the node for running flocker.

    :param bytes node: Node to provision.
    :param bytes username: Username to connect as.
    :param bytes distribution: See func:`task_install`
    :param PackageSource package_source: See func:`task_install`
    """
    commands = []
    commands += task_install_kernel()
    commands += task_install_flocker(package_source=package_source,
                                     distribution=distribution)
    commands += task_enable_docker()
    commands += task_disable_firewall()
    commands += task_create_flocker_pool_file()

    run_with_fabric(username=username, address=node, commands=commands)
