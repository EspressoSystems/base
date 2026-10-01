{
  description = "Base development environment and load generator tooling";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    rust-overlay = {
      url = "github:oxalica/rust-overlay";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    { nixpkgs, rust-overlay, ... }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "aarch64-darwin"
      ];
      forAllSystems =
        f:
        nixpkgs.lib.genAttrs systems (
          system:
          f (
            import nixpkgs {
              inherit system;
              overlays = [ rust-overlay.overlays.default ];
            }
          )
        );

      # Toolchain pinned by rust-toolchain.toml, plus editor support.
      toolchainFor =
        pkgs:
        (pkgs.rust-bin.fromRustupToolchainFile ./rust-toolchain.toml).override {
          extensions = [
            "rust-src"
            "rust-analyzer"
          ];
        };

      # Native dependencies needed to compile the workspace, matching
      # .github/actions/setup and etc/docker/Dockerfile.rust-services.
      buildDepsFor =
        pkgs: with pkgs; [
          (toolchainFor pkgs)
          pkg-config
          cmake
          clang
          protobuf
          openssl
          sqlite
          go
          git
        ];

      buildEnvFor = pkgs: {
        LIBCLANG_PATH = "${pkgs.libclang.lib}/lib";
        PROTOC = "${pkgs.protobuf}/bin/protoc";
        PKG_CONFIG_PATH = "${pkgs.openssl.dev}/lib/pkgconfig:${pkgs.sqlite.dev}/lib/pkgconfig";
      };

      exportsFor =
        pkgs:
        nixpkgs.lib.concatStrings (
          nixpkgs.lib.mapAttrsToList (name: value: "export ${name}=\"${value}\"\n") (buildEnvFor pkgs)
        );

      # Wraps a script so it runs from the repository root with the build env set.
      repoAppFor = pkgs: name: runtimeInputs: text: {
        type = "app";
        program = nixpkgs.lib.getExe (
          pkgs.writeShellApplication {
            inherit name runtimeInputs;
            text = ''
              ${exportsFor pkgs}
              cd "$(git rev-parse --show-toplevel)"
              ${text}
            '';
          }
        );
      };
    in
    {
      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell (
          buildEnvFor pkgs
          // {
            packages =
              buildDepsFor pkgs
              ++ (with pkgs; [
                just
                cargo-nextest
                sccache
                foundry
                docker-client
                docker-buildx
                actionlint
              ]);
          }
        );
      });

      apps = forAllSystems (pkgs: {
        # nix run .#loadgen -- crates/infra/load-tests/examples/devnet.yaml
        loadgen = repoAppFor pkgs "loadgen" (buildDepsFor pkgs) ''
          exec cargo run --locked --release -p base-load-tester-bin --bin base-load-tester -- "$@"
        '';

        # nix run .#loadgen-image  (loads base-loadgen:local into the local Docker daemon)
        loadgen-image = repoAppFor pkgs "loadgen-image" [ pkgs.git pkgs.docker-buildx ] ''
          exec docker-buildx bake \
            -f etc/docker/docker-bake.hcl \
            -f etc/docker/docker-bake.espresso.hcl \
            loadgen --load "$@"
        '';

        # nix run .#lint-ci
        lint-ci = repoAppFor pkgs "lint-ci" [ pkgs.git pkgs.actionlint ] ''
          exec actionlint "$@"
        '';
      });

      formatter = forAllSystems (pkgs: pkgs.nixfmt);
    };
}
