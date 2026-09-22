"""relativize-configs.sh: rewrite absolute install prefixes baked into .pc / .cmake
files to self-relative anchors (.pc -> ${pcfiledir}, .cmake -> ${CMAKE_CURRENT_LIST_DIR}),
so a package resolves correctly wherever it is laid down, including reuse that skips
relocate-me.sh. The helper is the extracted, portable (BSD+GNU sed) form of the block
that used to live inline in build_template.sh.
"""
import os
import subprocess
import tempfile

import bits_helpers

HELPER = os.path.join(os.path.dirname(bits_helpers.__file__), "relativize-configs.sh")


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def _run(root):
    subprocess.run(["bash", HELPER, root], check=True)


def test_pc_and_cmake_become_self_relative():
    with tempfile.TemporaryDirectory() as root:
        pc = os.path.join(root, "lib", "pkgconfig", "foo.pc")
        cm = os.path.join(root, "lib", "cmake", "Foo", "FooConfig.cmake")
        _write(pc, "prefix=%s\nincludedir=%s/include\nCflags: -I${includedir}\n" % (root, root))
        _write(cm, 'set(FOO_DIR "%s/include")\n' % root)
        _run(root)
        pc_txt = open(pc).read()
        cm_txt = open(cm).read()
        # from lib/pkgconfig, the package root is two levels up
        assert "prefix=${pcfiledir}/../..\n" in pc_txt
        assert "includedir=${pcfiledir}/../../include\n" in pc_txt
        # from lib/cmake/Foo, three levels up
        assert "${CMAKE_CURRENT_LIST_DIR}/../../../include" in cm_txt
        # no absolute prefix left anywhere
        assert root not in pc_txt
        assert root not in cm_txt


def test_pc_at_root_uses_bare_anchor():
    with tempfile.TemporaryDirectory() as root:
        pc = os.path.join(root, "foo.pc")
        _write(pc, "prefix=%s\n" % root)
        _run(root)
        assert open(pc).read() == "prefix=${pcfiledir}\n"


def test_relocatable_file_is_untouched():
    with tempfile.TemporaryDirectory() as root:
        pc = os.path.join(root, "lib", "pkgconfig", "clean.pc")
        original = "prefix=${pcfiledir}/../..\nCflags: -I${prefix}/include\n"
        _write(pc, original)
        _run(root)
        assert open(pc).read() == original


def test_idempotent_and_no_backup_left():
    with tempfile.TemporaryDirectory() as root:
        pc = os.path.join(root, "lib", "pkgconfig", "foo.pc")
        _write(pc, "prefix=%s\n" % root)
        _run(root)
        first = open(pc).read()
        _run(root)
        assert open(pc).read() == first
        # the sed -i.suffix backup must be cleaned up
        leftovers = [f for _, _, files in os.walk(root) for f in files if f.endswith(".bits-reloc")]
        assert leftovers == []
