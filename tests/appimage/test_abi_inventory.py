from package_linux.abi_inventory import required_versions


def test_needs_marker_without_symbol_and_not_provided_definitions():
    text = '''Version definition section '.gnu.version_d':
    Name: GLIBC_2.43
    Version needs section '.gnu.version_r':
    Name: GLIBC_ABI_GNU2_TLS Flags: none
    Name: GLIBC_2.39 Flags: none
    Name: GLIBCXX_3.4.30 Flags: none
    Name: CXXABI_1.3.13 Flags: none
    '''
    assert required_versions(text) == ['CXXABI_1.3.13', 'GLIBCXX_3.4.30',
                                      'GLIBC_2.39', 'GLIBC_ABI_GNU2_TLS']


def test_no_needs_table():
    assert required_versions('Version definition section Name: GLIBC_2.43') == []
