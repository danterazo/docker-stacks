# Reuse the locally available ROCm 7.14 image, pinned to its observed digest.
FROM blivioniag/vllm-rdna:v0.31.0-extras@sha256:16cbf6a09c879b2c69012c60bed4eb935e3029839bc641d1a9574931e8b9f127 AS build

ARG BUILD_JOBS=1
ARG LLAMA_COMMIT=e194cbddce45178467cef4afab0e3400ea357406
WORKDIR /src/llama.cpp
RUN git init . \
    && git remote add origin https://github.com/edwinbrowwn/llama.cpp-rdna2.git \
    && git fetch --depth 1 origin "${LLAMA_COMMIT}" \
    && git checkout --detach FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = "${LLAMA_COMMIT}"

# Keep the compile deliberately small; no GPU or model access is needed to build.
# RCCL is required (CMake fails rather than silently making a CPU-only build).
RUN cmake -S . -B /build -G Ninja \
      -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_PREFIX_PATH=/opt/rocm \
      -DCMAKE_HIP_COMPILER=/opt/rocm/llvm/bin/clang++ \
      -DCMAKE_HIP_ARCHITECTURES=gfx1030 \
      -DGPU_TARGETS=gfx1030 \
      -DGGML_HIP=ON \
      -DGGML_HIP_RCCL=ON \
      -DGGML_HIP_GRAPHS=ON \
      -DGGML_HIP_NO_VMM=ON \
      -DGGML_NATIVE=OFF \
      -DGGML_BACKEND_DL=OFF \
      -DLLAMA_BUILD_SERVER=ON \
      -DLLAMA_BUILD_TESTS=OFF \
      -DLLAMA_BUILD_SPEC_SIDECARS=OFF \
      -DLLAMA_BUILD_UI=OFF \
      -DLLAMA_USE_PREBUILT_UI=OFF \
    && cmake --build /build --target llama-server --parallel "${BUILD_JOBS}" \
    && test -x /build/bin/llama-server \
    && test -e /build/bin/libggml-hip.so \
    && ldd /build/bin/llama-server /build/bin/libggml-hip.so > /tmp/llama-ldd \
    && ! grep -q 'not found' /tmp/llama-ldd

FROM blivioniag/vllm-rdna:v0.31.0-extras@sha256:16cbf6a09c879b2c69012c60bed4eb935e3029839bc641d1a9574931e8b9f127
COPY --from=build /build/bin/ /opt/llama/bin/
ENV LD_LIBRARY_PATH=/opt/llama/bin:/usr/local/lib/python3.12/dist-packages/_rocm_sdk_libraries/lib:/usr/local/lib/python3.12/dist-packages/_rocm_sdk_core/lib:/usr/local/lib/python3.12/dist-packages/_rocm_sdk_core/lib/llvm/lib:/opt/rocm/lib
WORKDIR /opt/llama
ENTRYPOINT ["/opt/llama/bin/llama-server"]
