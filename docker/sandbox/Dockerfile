FROM e2bdev/code-interpreter:latest

ARG HTTP_PROXY
ARG HTTPS_PROXY

ENV HTTP_PROXY=${HTTP_PROXY} \
    HTTPS_PROXY=${HTTPS_PROXY} \
    http_proxy=${HTTP_PROXY} \
    https_proxy=${HTTPS_PROXY}

WORKDIR /workspace

USER root
RUN mkdir -p /workspace && chmod -R 777 /workspace

CMD ["/bin/bash"]