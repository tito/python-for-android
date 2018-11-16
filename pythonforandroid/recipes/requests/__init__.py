from pythonforandroid.recipe import PythonRecipe


class RequestsRecipe(PythonRecipe):
    version = '2.13.0'
    url = 'https://github.com/kennethreitz/requests/archive/v{version}.tar.gz'
<<<<<<< Updated upstream
    depends = [('hostpython2', 'hostpython3', 'hostpython3crystax'), 'setuptools']
=======
    depends = [('hostpython2', 'hostpython3crystax', 'hostpython3'), 'setuptools']
>>>>>>> Stashed changes
    site_packages_name = 'requests'
    call_hostpython_via_targetpython = False


recipe = RequestsRecipe()
