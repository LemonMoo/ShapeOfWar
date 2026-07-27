"""Generate a Windows VS_VERSION_INFO resource file for PyInstaller.

An exe with no version resource at all is anonymous to Windows: Explorer's
Details tab is blank, and SmartScreen/antivirus heuristics have nothing to go
on but the bytes. Embedding real product/company/version strings doesn't remove
the SmartScreen warning on an unsigned binary (only a code-signing certificate
does that), but it makes the app identifiable in the "More info" panel, in Task
Manager, and in Explorer -- and it's what a legitimate build is expected to
have.

Called by build.bat / build_launcher.bat; the generated file is passed to
PyInstaller via --version-file. Kept as a generator rather than two committed
static files so the version string lives in exactly one place per build script
instead of drifting out of sync with the release tag.

Usage:
    python make_version_file.py <out_path> <version> <product> <description> <exe_name>
"""
import sys

_TEMPLATE = '''VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={vers},
    prodvers={vers},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', {company!r}),
         StringStruct('FileDescription', {description!r}),
         StringStruct('FileVersion', {version!r}),
         StringStruct('InternalName', {internal!r}),
         StringStruct('OriginalFilename', {exe_name!r}),
         StringStruct('ProductName', {product!r}),
         StringStruct('ProductVersion', {version!r})])
      ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
'''

COMPANY = "LemonMoo"


def _version_tuple(version):
    """'0.06' / 'v0.06' / '0.0.6' -> a 4-int tuple Windows wants."""
    parts = version.lstrip("vV").split(".")
    nums = []
    for p in parts:
        try:
            nums.append(int(p))
        except ValueError:
            nums.append(0)
    while len(nums) < 4:
        nums.append(0)
    return tuple(nums[:4])


def main():
    if len(sys.argv) != 6:
        print(__doc__)
        return 1
    out_path, version, product, description, exe_name = sys.argv[1:6]
    text = _TEMPLATE.format(
        vers=_version_tuple(version),
        company=COMPANY,
        description=description,
        version=version,
        internal=exe_name.rsplit(".", 1)[0],
        exe_name=exe_name,
        product=product,
    )
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"wrote {out_path} (version {version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
