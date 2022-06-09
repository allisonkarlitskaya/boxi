# Boxi
A terminal emulator for use with Toolbox.

This is a thought-experiment app based around the idea of having a terminal emulator running on the host and the session inside of it running entirely inside of a container, with the kernel as the only intermediary.

This is accomplished by means of file descriptor passing of the pseudoterminal device from a small "agent" program running inside of the container.  The agent is started using the usual container tools (Toolbox, podman), but creating a session is done purely via sockets.
