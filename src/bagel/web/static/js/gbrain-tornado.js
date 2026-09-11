/**
 * GBrain tornado cone — cn-k12 / os-taxonomy visual contract.
 *
 * Tech notes (why not default 3d-force-graph spheres):
 * - Reference apps use THREE.MeshBasicMaterial (+ AdditiveBlending), NOT lit Phong
 *   spheres — that specular highlight is the "plastic" look.
 * - Default edges are hair-thin + low opacity; only focus neighborhood brightens.
 * - Layout: golden helix + height→radius cone, tip-grow, auto-rotate.
 */
(function (global) {
  "use strict";

  var GOLDEN = Math.PI * (3 - Math.sqrt(5));
  var TWIST_TURNS = 1.75;
  var MIN_R = 12;
  var MAX_R = 175;
  var RADIAL_K = 0.14;

  // Soft pastel palette (desaturated, ethereal — matches fig.1/2)
  var SOFT_BY_KIND = {
    item: "#c9d6ef",
    topic: "#8ec5e8",
    cluster: "#e0b8d0",
    type: "#9eb0d8",
    source: "#d2c09a",
    institution: "#95cbb8",
    category: "#b5a8d8",
    tag: "#9aa6b8",
  };

  function getTHREE() {
    if (global.THREE) return global.THREE;
    try {
      var g = ForceGraph3D()(document.createElement("div"));
      var scene = g.scene && g.scene();
      if (scene && scene.constructor) {
        // Best-effort: not reliable; require window.THREE from CDN.
      }
    } catch (e) {}
    return global.THREE || null;
  }

  function targetRadius(t) {
    return MIN_R + Math.max(0, Math.min(1, t)) * (MAX_R - MIN_R);
  }

  function softColor(n) {
    if (n && n.color && /^#/.test(n.color) && n.kind === "item" && n.type_label) {
      // Keep channel tint but pull toward pastel.
      return mixHex(n.color, SOFT_BY_KIND.item || "#c9d6ef", 0.55);
    }
    return (n && SOFT_BY_KIND[n.kind]) || (n && n.color) || "#9aa6b8";
  }

  function mixHex(a, b, t) {
    function parse(h) {
      h = String(h || "").replace("#", "");
      if (h.length === 3)
        h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
      return [
        parseInt(h.slice(0, 2), 16) || 0,
        parseInt(h.slice(2, 4), 16) || 0,
        parseInt(h.slice(4, 6), 16) || 0,
      ];
    }
    var A = parse(a);
    var B = parse(b);
    var r = Math.round(A[0] + (B[0] - A[0]) * t);
    var g = Math.round(A[1] + (B[1] - A[1]) * t);
    var bl = Math.round(A[2] + (B[2] - A[2]) * t);
    return (
      "#" +
      [r, g, bl]
        .map(function (x) {
          return ("0" + Math.max(0, Math.min(255, x)).toString(16)).slice(-2);
        })
        .join("")
    );
  }

  function nodeRadius(n) {
    var kindBase = {
      cluster: 2.8,
      topic: 2.1,
      type: 1.55,
      source: 1.4,
      institution: 1.5,
      category: 1.3,
      tag: 1.1,
      item: 0.72,
    };
    var base = kindBase[n.kind] || 1.15;
    var w = Math.sqrt(Math.max(1, n.value || n.val || 1));
    return base * (0.75 + Math.min(1.6, w * 0.12));
  }

  function prepareNodes(rawNodes, opts) {
    opts = opts || {};
    var grow = opts.growFromTip !== false;
    var nodes = (rawNodes || []).map(function (n, i) {
      var h = typeof n.fy === "number" ? n.fy : n.height || 0;
      return Object.assign({}, n, {
        __rawH: h,
        __idx: i,
        __soft: softColor(n),
        val: n.val || Math.max(1, Math.min(10, 2 + (n.value || 1) * 0.35)),
        __visible: true,
      });
    });
    var heights = nodes.map(function (n) {
      return n.__rawH || 1;
    });
    var maxH = heights.length ? Math.max.apply(null, heights) : 1;
    if (!isFinite(maxH) || maxH <= 0) maxH = 1;
    var midY = maxH * 0.5;
    nodes.forEach(function (n) {
      var t = Math.max(0, Math.min(1, (n.__rawH || 0) / maxH));
      var ang = (n.__idx * GOLDEN + t * TWIST_TURNS * Math.PI * 2) % (Math.PI * 2);
      var r0 = targetRadius(t * 0.55);
      n.__t = t;
      n.__ang = ang;
      n.__targetFy = (n.__rawH || 0) - midY;
      n.fy = grow ? -midY : n.__targetFy;
      n.x = Math.cos(ang) * r0;
      n.z = Math.sin(ang) * r0;
      n.__r = nodeRadius(n);
    });
    return { nodes: nodes, maxH: maxH, midY: midY };
  }

  function prepareLinks(rawLinks) {
    return (rawLinks || []).map(function (l) {
      return {
        source: l.source,
        target: l.target,
        relation: l.relation || "about",
        value: l.value || 1,
      };
    });
  }

  function paintStageBackground(el) {
    if (!el) return;
    el.style.background =
      "radial-gradient(ellipse 68% 58% at 50% 40%, #0b1a36 0%, #050b18 50%, #010208 100%)";
  }

  function linkEnds(l) {
    return {
      s: (l.source && l.source.id) || l.source,
      t: (l.target && l.target.id) || l.target,
    };
  }

  function mountTornadoGraph(el, data, opts) {
    opts = opts || {};
    if (!el || typeof ForceGraph3D === "undefined") return null;
    var THREE = getTHREE();
    paintStageBackground(el);

    var prepared = prepareNodes(data.nodes || [], { growFromTip: opts.growFromTip !== false });
    var allNodes = prepared.nodes;
    var allLinks = prepareLinks(data.links || []);
    var maxH = prepared.maxH;
    var midY = prepared.midY;
    var bg = opts.backgroundColor || "#040a18";
    var highlightKeys = null; // null = idle; object map = focus neighborhood

    function nodeHi(n) {
      return !highlightKeys || !!highlightKeys[n.id];
    }
    function linkHi(l) {
      if (!highlightKeys) return false;
      var e = linkEnds(l);
      return !!(highlightKeys[e.s] && highlightKeys[e.t]);
    }

    function applyMeshStyle(n, mesh) {
      if (!mesh || !mesh.material) return;
      var hi = nodeHi(n);
      var idle = !highlightKeys;
      var opacity = idle ? (n.kind === "item" ? 0.62 : 0.78) : hi ? 0.98 : 0.1;
      var scale = idle ? 1 : hi ? 1.35 : 0.78;
      var col = hi && highlightKeys ? mixHex(n.__soft || softColor(n), "#e8f4ff", 0.35) : n.__soft || softColor(n);
      if (highlightKeys && hi) col = mixHex(col, "#ffffff", 0.25);
      mesh.material.color.set(col);
      mesh.material.opacity = opacity;
      mesh.material.transparent = true;
      mesh.material.depthWrite = opacity > 0.5;
      mesh.scale.setScalar(scale);
      mesh.material.needsUpdate = true;
    }

    var Graph = ForceGraph3D()(el)
      .graphData({ nodes: allNodes.slice(), links: allLinks.slice() })
      .backgroundColor(bg)
      .showNavInfo(false)
      .nodeId("id")
      .nodeLabel(
        opts.nodeLabel ||
          function (n) {
            return [
              n.name || "",
              (n.kind_label || n.kind || "") + (n.type_label ? " · " + n.type_label : ""),
            ].join("\n");
          }
      )
      .nodeOpacity(1)
      .linkColor(function (l) {
        if (linkHi(l)) return "#9ad4ff";
        if (highlightKeys) return "#152033";
        return l.relation === "prerequisite" ? "#2a3550" : "#1a2438";
      })
      .linkWidth(function (l) {
        if (linkHi(l)) return 1.65;
        if (highlightKeys) return 0.08;
        return 0.18;
      })
      .linkOpacity(function (l) {
        if (linkHi(l)) return 0.88;
        if (highlightKeys) return 0.04;
        return l.relation === "prerequisite" ? 0.14 : 0.1;
      })
      .linkDirectionalParticles(function (l) {
        return linkHi(l) ? 2 : 0;
      })
      .linkDirectionalParticleWidth(1.0)
      .linkDirectionalParticleSpeed(0.005)
      .onNodeDragEnd(function (node) {
        node.fy = node.__targetFy != null ? node.__targetFy : node.fy;
      });

    if (THREE) {
      Graph.nodeThreeObject(function (n) {
        var r = n.__r || nodeRadius(n);
        var geo = new THREE.SphereGeometry(r, 14, 12);
        var mat = new THREE.MeshBasicMaterial({
          color: n.__soft || softColor(n),
          transparent: true,
          opacity: n.kind === "item" ? 0.62 : 0.78,
          depthWrite: false,
          fog: true,
        });
        // Additive glow for hubs — ethereal, not plastic specular.
        if (n.kind === "cluster" || n.kind === "topic" || n.kind === "type") {
          mat.blending = THREE.AdditiveBlending;
          mat.opacity = 0.72;
        }
        var mesh = new THREE.Mesh(geo, mat);
        applyMeshStyle(n, mesh);
        return mesh;
      });
      Graph.nodeThreeObjectExtend(false);
    } else {
      // Fallback without THREE global: still shrink + desaturate via accessors.
      Graph.nodeVal(function (n) {
        return (n.__r || 1) * 2.2;
      }).nodeColor(function (n) {
        if (highlightKeys && !nodeHi(n)) return "#1a2233";
        if (highlightKeys && nodeHi(n)) return mixHex(n.__soft || "#aabbcc", "#ffffff", 0.35);
        return n.__soft || softColor(n);
      }).nodeOpacity(0.7);
    }

    if (typeof opts.onNodeClick === "function") {
      Graph.onNodeClick(opts.onNodeClick);
    }

    Graph.d3Force("charge").strength(opts.chargeStrength != null ? opts.chargeStrength : -72);
    var linkForce = Graph.d3Force("link");
    if (linkForce) linkForce.distance(opts.linkDistance != null ? opts.linkDistance : 32);
    Graph.d3Force("y", null);
    Graph.d3Force("center", null);

    Graph.onEngineTick(function () {
      allNodes.forEach(function (n) {
        if (n.__visible === false) return;
        var t = n.__t != null ? n.__t : Math.max(0, Math.min(1, (n.__rawH || 0) / maxH));
        var targetR = targetRadius(t);
        var x = n.x || 0;
        var z = n.z || 0;
        var r = Math.hypot(x, z) || 0.001;
        var k = RADIAL_K;
        n.vx = (n.vx || 0) + (x * (targetR / r) - x) * k;
        n.vz = (n.vz || 0) + (z * (targetR / r) - z) * k;
        if (typeof n.__ang === "number") {
          var cur = Math.atan2(z, x);
          var dAng = n.__ang - cur;
          while (dAng > Math.PI) dAng -= Math.PI * 2;
          while (dAng < -Math.PI) dAng += Math.PI * 2;
          var tang = 0.035 * dAng * targetR;
          n.vx += -Math.sin(cur) * tang;
          n.vz += Math.cos(cur) * tang;
        }
      });
    });

    var controls = Graph.controls();
    if (controls) {
      controls.autoRotate = opts.autoRotate !== false;
      controls.autoRotateSpeed = opts.autoRotateSpeed != null ? opts.autoRotateSpeed : 0.36;
      controls.enableDamping = true;
    }

    function refreshHighlightStyles() {
      allNodes.forEach(function (n) {
        if (n.__threeObj) applyMeshStyle(n, n.__threeObj);
      });
      // Re-bind data so link accessors re-paint widths / colors / particles.
      var gd = Graph.graphData();
      Graph.graphData({ nodes: gd.nodes, links: gd.links });
    }

    function setHighlight(keys) {
      if (!keys) {
        highlightKeys = null;
      } else if (Array.isArray(keys)) {
        highlightKeys = {};
        keys.forEach(function (k) {
          highlightKeys[k] = true;
        });
      } else {
        highlightKeys = keys;
      }
      refreshHighlightStyles();
    }

    function frameCone(ms) {
      try {
        Graph.zoomToFit(ms || 0, opts.fitPadding != null ? opts.fitPadding : 48);
      } catch (e) {
        Graph.cameraPosition(
          { x: 0, y: maxH * 0.04, z: Math.max(300, maxH * 1.5) },
          { x: 0, y: 0, z: 0 },
          0
        );
      }
    }

    function fitSize() {
      var w = el.clientWidth || opts.width || 900;
      var h = el.clientHeight || opts.height || 720;
      Graph.width(w).height(h);
    }

    fitSize();
    frameCone(0);

    if (opts.growFromTip !== false) {
      var t0 = performance.now();
      var duration = opts.growMs != null ? opts.growMs : 3600;
      (function grow() {
        var t = Math.min(1, (performance.now() - t0) / duration);
        var eased = 1 - Math.pow(1 - t, 3);
        allNodes.forEach(function (n) {
          n.fy = -midY + (n.__rawH || 0) * eased;
        });
        if (t < 1) {
          requestAnimationFrame(grow);
        } else {
          allNodes.forEach(function (n) {
            n.fy = n.__targetFy;
          });
          frameCone(700);
        }
      })();
    } else {
      setTimeout(function () {
        frameCone(500);
      }, 120);
    }

    return {
      graph: Graph,
      allNodes: allNodes,
      allLinks: allLinks,
      maxH: maxH,
      midY: midY,
      frameCone: frameCone,
      fitSize: fitSize,
      setHighlight: setHighlight,
      setGraphData: function (nodes, links) {
        Graph.graphData({ nodes: nodes, links: links });
        refreshHighlightStyles();
      },
      destroy: function () {
        try {
          Graph.pauseAnimation();
        } catch (e) {}
        try {
          el.innerHTML = "";
        } catch (e2) {}
      },
    };
  }

  global.BagelGbrainTornado = {
    prepareNodes: prepareNodes,
    prepareLinks: prepareLinks,
    mountTornadoGraph: mountTornadoGraph,
    targetRadius: targetRadius,
    softColor: softColor,
    MIN_R: MIN_R,
    MAX_R: MAX_R,
  };
})(typeof window !== "undefined" ? window : globalThis);
