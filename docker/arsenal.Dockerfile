# Herramientas de Parrot/Kali que no corren nativas en macOS. Sólo para eso:
# el clonador, urlcrazy y lo demás siguen siendo nativos.
FROM kalilinux/kali-rolling

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      set beef-xss msfpc wifi-honey fiked isr-evilgrade sniffjoke thc-ipv6 \
      dsniff yersinia tshark responder evil-ssdp golang-go make ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# convoC2 no está empaquetado en Kali: se compila aquí (server linux + agente Windows).
COPY vendor/convoc2 /src/convoc2
RUN cd /src/convoc2 && make agent server_amd64 server_arm64 compress \
 && mkdir -p /opt/convoc2 \
 && cp build/server/convoC2_server_* /opt/convoc2/ \
 && cp build/agent/convoC2_agent.exe /opt/convoc2/ \
 && arch=$(uname -m) \
 && case "$arch" in aarch64|arm64) arch=arm64 ;; x86_64|amd64) arch=amd64 ;; esac \
 && ln -s "/opt/convoc2/convoC2_server_${arch}" /usr/local/bin/convoC2

WORKDIR /work
ENTRYPOINT ["/bin/bash", "-lc"]
