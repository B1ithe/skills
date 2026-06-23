FROM node:latest
RUN npm install -g depyo
COPY decompile.sh /decompile.sh
RUN chmod +x /decompile.sh
ENTRYPOINT ["/decompile.sh"]
