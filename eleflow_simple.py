from mininet.topo import Topo

class MyTopo(Topo):
    def build(self):

        # Spine switches
        s4 = self.addSwitch('s4')
        s5 = self.addSwitch('s5')

        # Leaf switches
        s1 = self.addSwitch('s1')
        s2 = self.addSwitch('s2')
        s3 = self.addSwitch('s3')

        # Hosts
        h1 = self.addHost('h1')
        h2 = self.addHost('h2')
        h3 = self.addHost('h3')
        h4 = self.addHost('h4')
        h5 = self.addHost('h5')
        h6 = self.addHost('h6')

        # Host → Leaf links
        self.addLink(h1, s1)
        self.addLink(h2, s1)

        self.addLink(h3, s2)
        self.addLink(h4, s2)

        self.addLink(h5, s3)
        self.addLink(h6, s3)

        # Leaf → Spine links
        self.addLink(s1, s4)
        self.addLink(s1, s5)

        self.addLink(s2, s4)
        self.addLink(s2, s5)

        self.addLink(s3, s4)
        self.addLink(s3, s5)

# Rejestracja topologii
topos = {
    'mytopo': (lambda: MyTopo())
}
