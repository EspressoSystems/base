# Espresso fork targets. Load together with the upstream bake file:
#   docker buildx bake -f etc/docker/docker-bake.hcl -f etc/docker/docker-bake.espresso.hcl loadgen --load

target "loadgen" {
  inherits = ["_rust-service-common"]
  target = "loadgen"
  args = {
    CARGO_CHEF_ARGS = "--package base-load-tester-bin"
    SCCACHE_CACHE_ID = "rust-services-loadgen-sccache"
  }
  tags = ["base-loadgen:local"]
}
