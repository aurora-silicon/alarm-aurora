"""Desktop images hand owner setup to the desktop after a splash disk prompt."""
from pathlib import Path
import os
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
BUILD_IMAGE = (ROOT/'scripts/build-image').read_text()
PROFILES = ('arch-kde', 'arch-gnome', 'arch-minimal')


def heredoc(path):
    match = re.search(r'cat > "\$mountroot/' + re.escape(path) + r"\" <<'EOF'\n(.*?)\nEOF\n", BUILD_IMAGE, re.S)
    assert match, path
    return match.group(1) + '\n'


def profile_packages(profile):
    match = re.search(r'(?m)^  ' + re.escape(profile) + r'\) packages\+=\(([^)]*)\);;$', BUILD_IMAGE)
    return match.group(1).split() if match else []


def bash(script, *args):
    return subprocess.run(['bash', '-c', script, 'test', *args], check=True, text=True,
                          capture_output=True, env={**os.environ, 'LC_ALL': 'C.UTF-8'}).stdout


class DesktopFirstBootTests(unittest.TestCase):
    def test_each_desktop_installs_its_owner_setup_and_the_splash(self):
        self.assertIn('plasma-setup', profile_packages('arch-kde'))
        self.assertIn('gnome-initial-setup', profile_packages('arch-gnome'))
        for profile in ('arch-kde', 'arch-gnome'):
            self.assertIn('plymouth', profile_packages(profile))
        self.assertEqual(profile_packages('arch-minimal'), [])
        self.assertNotIn('plymouth', re.search(r'(?s)^packages=\((.*?)\)\n', BUILD_IMAGE, re.M).group(1).split())
        self.assertRegex(BUILD_IMAGE, r'(?m)^  arch-kde\) chroot "\$mountroot" systemctl enable sddm plasma-setup\.service;')
        self.assertNotRegex(BUILD_IMAGE, r'(?m)^  arch-gnome\).*plasma-setup')

    def test_splash_and_hook_are_configured_before_the_initramfs(self):
        initramfs = BUILD_IMAGE.index('chroot "$mountroot" mkinitcpio -P')
        theme = BUILD_IMAGE.index('chroot "$mountroot" plymouth-set-default-theme spinner\n')
        hook = BUILD_IMAGE.index('/etc/mkinitcpio.conf.d/95-aurora-plymouth.conf')
        self.assertLess(theme, initramfs)
        self.assertLess(hook, initramfs)
        self.assertIn('if [[ $profile != arch-minimal ]]; then\n  # The splash theme', BUILD_IMAGE)

    def test_plymouth_follows_systemd_and_keeps_the_aurora_hook_order(self):
        common = ROOT/'packages/aurora-boot/90-aurora.conf'
        dropin = heredoc('etc/mkinitcpio.conf.d/95-aurora-plymouth.conf')
        expected = []
        for hook in bash('source "$1"; printf "%s\\n" "${HOOKS[@]}"', str(common)).split():
            expected.append(hook)
            if hook == 'systemd':
                expected.append('plymouth')
        self.assertEqual(expected[:3], ['base', 'systemd', 'plymouth'])
        self.assertLess(expected.index('plymouth'), expected.index('sd-encrypt'))
        # The drop-in leaves no helper variables behind in mkinitcpio's shell.
        show = 'source "$1"; eval "$2"; [[ -z ${_aurora_hook+x}${_aurora_hooks+x} ]]; printf "%s\\n" "${HOOKS[@]}"'
        self.assertEqual(bash(show, str(common), dropin).split(), expected)
        # Reading the drop-in twice, or after a plymouth hook elsewhere, leaves one plymouth.
        self.assertEqual(bash('source "$1"; HOOKS+=(plymouth); eval "$2"; eval "$2"; printf "%s\\n" "${HOOKS[@]}"',
                              str(common), dropin).split(), expected)
        self.assertEqual(bash('HOOKS="base systemd block"; eval "$1"; printf "%s\\n" "${HOOKS[@]}"', dropin).split(),
                         ['base', 'systemd', 'plymouth', 'block'])
        # mkinitcpio reads drop-ins in version order after the main file.
        names = bash('printf "%s\\n" 95-aurora-plymouth.conf 90-aurora.conf | sort -V').split()
        self.assertEqual(names, ['90-aurora.conf', '95-aurora-plymouth.conf'])

    def test_only_desktops_boot_to_the_splash(self):
        block = re.search(r"(?m)^cmdline='.*\n.*\n", BUILD_IMAGE).group(0)
        for profile in PROFILES:
            words = bash(f'profile=$1; {block} printf "%s" "$cmdline"', profile).split()
            self.assertEqual(words[:4], ['quiet', 'loglevel=3', 'rd.udev.log_level=3', 'systemd.show_status=auto'])
            self.assertEqual('splash' in words, profile != 'arch-minimal', profile)
        self.assertIn('printf \'GRUB_CMDLINE_LINUX_DEFAULT="%s"\\n\' "$cmdline" >> "$mountroot/etc/default/grub"', BUILD_IMAGE)

    def test_sddm_keeps_the_splash_until_the_greeter_like_gdm(self):
        unit = heredoc('etc/systemd/system/sddm.service.d/10-aurora-plymouth.conf')
        self.assertIn('Conflicts=plymouth-quit.service\n', unit)
        self.assertIn('OnFailure=plymouth-quit.service\n', unit)
        self.assertRegex(unit, r'(?m)^ExecStartPre=-/usr/bin/timeout .* /usr/bin/plymouth quit$')
        self.assertIn('if [[ $profile == arch-kde ]]; then\n  # GDM replaces plymouth-quit.service', BUILD_IMAGE)


class PlasmaSetupRecipeTests(unittest.TestCase):
    def recipe(self, expression):
        return bash('cd "$1"; source ./PKGBUILD; ' + expression, str(ROOT/'packages/plasma-setup')).split('\n')[:-1]

    def test_release_tarball_is_digest_pinned(self):
        version, = self.recipe('printf "%s\\n" "$pkgver"')
        source, = self.recipe('printf "%s\\n" "${source[@]}"')
        digest, = self.recipe('printf "%s\\n" "${sha256sums[@]}"')
        self.assertEqual(source, f'https://download.kde.org/stable/plasma/{version}/plasma-setup-{version}.tar.xz')
        self.assertRegex(digest, r'^[0-9a-f]{64}$')

    def test_runtime_dependencies_cover_the_wizard_modules(self):
        depends = set(self.recipe('printf "%s\\n" "${depends[@]}"'))
        for name in ['kirigami-addons', 'plasma-nm', 'qt6-location', 'qt6-base', 'qt6-declarative', 'qt6-svg',
                     'kauth', 'kcoreaddons', 'ki18n', 'kpackage', 'kconfig', 'libkscreen', 'kwindowsystem',
                     'plasma-workspace', 'plasma-desktop', 'kirigami', 'kitemmodels', 'polkit', 'shadow', 'systemd']:
            self.assertIn(name, depends)
        self.assertEqual(self.recipe('printf "%s\\n" "${arch[@]}"'), ['aarch64'])

    def test_helpers_install_where_the_unit_and_autostart_expect_them(self):
        recipe = (ROOT/'packages/plasma-setup/PKGBUILD').read_text()
        self.assertIn('-DCMAKE_INSTALL_PREFIX=/usr', recipe)
        self.assertIn('-DKDE_INSTALL_LIBEXECDIR=lib', recipe)
        self.assertIn('DESTDIR="$pkgdir" cmake --install build', recipe)


if __name__ == '__main__':
    unittest.main()
