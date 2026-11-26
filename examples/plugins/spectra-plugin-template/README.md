# spectra-plugin-template

A starting point for a Spectra Inspector plugin that people install with `pip`.

1. Copy this folder and rename the package (`src/spectra_plugin_template`), the project `name` and the entry point in `pyproject.toml`.
2. Edit `PLUGIN` and `register(ctx)` in `src/<package>/__init__.py`. The API is documented in [docs/plugins.md](../../../docs/plugins.md).
3. Try it in the environment Spectra runs in:

   ```powershell
   python -m pip install -e .
   python -m spectra
   ```

   It shows up in **Plugins > Plugin Manager** with the source "package". Tick it to enable it.
4. Publish it: `python -m build` and `python -m twine upload dist/*`. Users then run `pip install <your-project>`.

The entry point group is `spectra_inspector.plugins`; the entry point name is the plugin id and its value is the module that defines `PLUGIN` and `register(ctx)`.
