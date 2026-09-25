import { useMemo, useState } from "react";
import {
  Bell,
  Bookmark,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Clock3,
  Crown,
  Flame,
  Flag,
  Hash,
  LayoutDashboard,
  Lock,
  MessageCircle,
  MoreHorizontal,
  PenLine,
  Pin,
  Plus,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Star,
  Tag,
  ThumbsUp,
  TrendingUp,
  Trophy,
  Users,
  X,
  Zap,
  Activity,
  BarChart3,
  Download,
  FileSpreadsheet,
  Filter,
  RefreshCw,
  SlidersHorizontal,
  UsersRound,
} from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from "recharts";
import { toast } from "sonner";
import * as XLSX from "xlsx";

type Topic = {
  id: number;
  title: string;
  body: string;
  category: string;
  author: string;
  handle: string;
  initials: string;
  time: string;
  replies: number;
  views: number;
  likes: number;
  tags: string[];
  pinned?: boolean;
  hot?: boolean;
  solved?: boolean;
  badge: string;
  color: string;
};

const categories = [
  { label: "Tüm konular", count: 248, icon: Hash },
  { label: "Maç sohbeti", count: 86, icon: Flame },
  { label: "Transfer merkezi", count: 54, icon: Zap },
  { label: "Crypto & Web3", count: 42, icon: Sparkles },
  { label: "App Crypto 24", count: 37, icon: LayoutDashboard },
  { label: "Off-topic", count: 29, icon: MessageCircle },
];

const initialTopics: Topic[] = [
  {
    id: 1,
    title: "Derbi gecesi: maçın kırılma anı sizce neydi?",
    body: "İlk yarıdaki pres ve ikinci yarıda yapılan değişiklikler maçın seyrini tamamen değiştirdi. Siz hangi dakikayı dönüm noktası olarak görüyorsunuz?",
    category: "Maç sohbeti",
    author: "Mert Yılmaz",
    handle: "@merty",
    initials: "MY",
    time: "12 dk önce",
    replies: 42,
    views: 1284,
    likes: 96,
    tags: ["#derbi", "#canlı"],
    pinned: true,
    hot: true,
    badge: "Topluluk elçisi",
    color: "#7c5cff",
  },
  {
    id: 2,
    title: "Bu yazın en iyi transferi kim olacak? Erken tahminler",
    body: "Scout raporlarınızı, maaş dengelerini ve takım ihtiyaçlarını aynı başlıkta toplayalım. Kaynaklı yorumlarınızı bekliyorum.",
    category: "Transfer merkezi",
    author: "Ece Kaya",
    handle: "@ecek",
    initials: "EK",
    time: "38 dk önce",
    replies: 31,
    views: 874,
    likes: 64,
    tags: ["#transfer", "#scout"],
    hot: true,
    badge: "Analist",
    color: "#ef6b8a",
  },
  {
    id: 3,
    title: "Yeni başlayanlar için cüzdan güvenliği: 7 temel kural",
    body: "Seed phrase, donanım cüzdanı ve ağ ücretleri konusunda herkesin bilmesi gereken kısa bir kontrol listesi hazırladım.",
    category: "Crypto & Web3",
    author: "Alp Demir",
    handle: "@alpchain",
    initials: "AD",
    time: "1 sa önce",
    replies: 18,
    views: 662,
    likes: 81,
    tags: ["#güvenlik", "#web3"],
    solved: true,
    badge: "Uzman üye",
    color: "#33c9a5",
  },
  {
    id: 4,
    title: "App Crypto 24 için hangi özelliği önce ekleyelim?",
    body: "Topluluğun ürün yol haritasına katkı vermesini istiyoruz. Bildirimler, kişiselleştirilmiş akış ve takım odaları arasında oy verelim.",
    category: "App Crypto 24",
    author: "Selin Aydın",
    handle: "@selinapp",
    initials: "SA",
    time: "2 sa önce",
    replies: 27,
    views: 512,
    likes: 53,
    tags: ["#ürün", "#anket"],
    badge: "Kurucu ekip",
    color: "#f1a94b",
  },
  {
    id: 5,
    title: "Gece vardiyası burada mı? Serbest sohbet alanı",
    body: "Günün gündeminden bağımsız, topluluğun tanışması ve sohbet etmesi için açık alan. Yeni gelenlere hoş geldin deyin.",
    category: "Off-topic",
    author: "Bora Çetin",
    handle: "@borac",
    initials: "BÇ",
    time: "3 sa önce",
    replies: 76,
    views: 1438,
    likes: 112,
    tags: ["#sohbet", "#tanışma"],
    badge: "Aktif üye",
    color: "#4e9bff",
  },
];

const badgeList = [
  { icon: ShieldCheck, name: "Topluluk elçisi", detail: "50 kişiye faydalı yanıt", tone: "violet" },
  { icon: Trophy, name: "İlk 10", detail: "Haftanın en aktifleri", tone: "gold" },
  { icon: MessageCircle, name: "Sohbet ustası", detail: "100 yanıt gönderdi", tone: "blue" },
  { icon: Sparkles, name: "Erken destekçi", detail: "Topluluk kurucularından", tone: "mint" },
];

const activityData = {
  "7": [
    { day: "Pzt", users: 92, replies: 138, topics: 18, views: 420 }, { day: "Sal", users: 114, replies: 176, topics: 23, views: 548 },
    { day: "Çar", users: 128, replies: 201, topics: 27, views: 622 }, { day: "Per", users: 121, replies: 184, topics: 25, views: 591 },
    { day: "Cum", users: 156, replies: 247, topics: 31, views: 741 }, { day: "Cmt", users: 181, replies: 296, topics: 38, views: 904 },
    { day: "Paz", users: 148, replies: 224, topics: 29, views: 682 },
  ],
  "30": [
    { day: "1. hf", users: 612, replies: 804, topics: 108, views: 2630 }, { day: "2. hf", users: 754, replies: 1038, topics: 136, views: 3280 },
    { day: "3. hf", users: 891, replies: 1291, topics: 171, views: 4110 }, { day: "4. hf", users: 1042, replies: 1484, topics: 206, views: 4980 },
  ],
  "90": [
    { day: "Oca", users: 1840, replies: 2920, topics: 384, views: 10600 }, { day: "Şub", users: 2210, replies: 3440, topics: 462, views: 12400 },
    { day: "Mar", users: 2580, replies: 4010, topics: 541, views: 14100 }, { day: "Nis", users: 2841, replies: 4660, topics: 628, views: 16300 },
  ],
} as const;

const memberRows = [
  { name: "Mert Yılmaz", initials: "MY", role: "Topluluk elçisi", status: "Aktif", topics: 84, replies: 312, lastActive: "2 dk önce", color: "#7c5cff" },
  { name: "Ece Kaya", initials: "EK", role: "Analist", status: "Aktif", topics: 61, replies: 184, lastActive: "8 dk önce", color: "#ef6b8a" },
  { name: "Alp Demir", initials: "AD", role: "Uzman üye", status: "Aktif", topics: 47, replies: 156, lastActive: "21 dk önce", color: "#33c9a5" },
  { name: "Bora Çetin", initials: "BÇ", role: "Aktif üye", status: "Uzakta", topics: 39, replies: 142, lastActive: "1 sa önce", color: "#4e9bff" },
  { name: "Selin Aydın", initials: "SA", role: "Kurucu ekip", status: "Aktif", topics: 32, replies: 98, lastActive: "2 sa önce", color: "#f1a94b" },
];

const channelActivity = [
  { name: "Maç sohbeti", topics: 86, replies: 624, color: "#8d72ff" },
  { name: "Transfer merkezi", topics: 54, replies: 418, color: "#ef6b8a" },
  { name: "Crypto & Web3", topics: 42, replies: 302, color: "#33c9a5" },
  { name: "App Crypto 24", topics: 37, replies: 276, color: "#f1bd61" },
  { name: "Off-topic", topics: 29, replies: 188, color: "#4e9bff" },
];

const userSegments = [
  { name: "Aktif", value: 128, color: "#8d72ff" },
  { name: "Uzakta", value: 74, color: "#54d7d0" },
  { name: "Yeni", value: 38, color: "#f1bd61" },
];

function Avatar({ initials, color, small = false }: { initials: string; color: string; small?: boolean }) {
  return (
    <div className={`avatar ${small ? "avatar-small" : ""}`} style={{ background: `linear-gradient(135deg, ${color}, #1d2141)` }}>
      {initials}
    </div>
  );
}

function BadgePill({ name }: { name: string }) {
  return <span className="badge-pill"><Sparkles size={12} />{name}</span>;
}

export default function Home() {
  const [topics, setTopics] = useState(initialTopics);
  const [activeCategory, setActiveCategory] = useState("Tüm konular");
  const [activeNav, setActiveNav] = useState("Forum");
  const [sort, setSort] = useState("Son aktiviteler");
  const [search, setSearch] = useState("");
  const [liked, setLiked] = useState<number[]>([]);
  const [saved, setSaved] = useState<number[]>([]);
  const [showComposer, setShowComposer] = useState(false);
  const [showProfile, setShowProfile] = useState(false);
  const [selectedTopic, setSelectedTopic] = useState<Topic | null>(null);
  const [newTitle, setNewTitle] = useState("");
  const [newBody, setNewBody] = useState("");
  const [newCategory, setNewCategory] = useState("Maç sohbeti");

  const filteredTopics = useMemo(() => {
    const result = topics.filter((topic) => {
      const matchesCategory = activeCategory === "Tüm konular" || topic.category === activeCategory;
      const needle = search.toLowerCase();
      const matchesSearch = !needle || `${topic.title} ${topic.body} ${topic.author} ${topic.tags.join(" ")}`.toLowerCase().includes(needle);
      return matchesCategory && matchesSearch;
    });
    if (sort === "En çok konuşulan") return [...result].sort((a, b) => b.replies - a.replies);
    if (sort === "En popüler") return [...result].sort((a, b) => b.likes - a.likes);
    return result;
  }, [activeCategory, search, sort, topics]);

  const toggleLike = (id: number) => {
    setLiked((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  };

  const toggleSave = (id: number) => {
    setSaved((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
    toast.success(saved.includes(id) ? "Kaydedilenlerden çıkarıldı" : "Konu kaydedildi");
  };

  const createTopic = () => {
    if (!newTitle.trim() || !newBody.trim()) {
      toast.error("Başlık ve içerik alanlarını doldurmalısın.");
      return;
    }
    const topic: Topic = {
      id: Date.now(), title: newTitle, body: newBody, category: newCategory,
      author: "Sen", handle: "@ben", initials: "SN", time: "şimdi", replies: 0, views: 1, likes: 0,
      tags: ["#yeni"], badge: "Yeni üye", color: "#f1a94b",
    };
    setTopics((current) => [topic, ...current]);
    setNewTitle(""); setNewBody(""); setShowComposer(false);
    toast.success("Konun topluluğa gönderildi.");
  };

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand" onClick={() => { setActiveNav("Forum"); setActiveCategory("Tüm konular"); }}>
          <div className="brand-mark"><Zap size={18} fill="currentColor" /></div>
          <div><strong>MACWEB</strong><span>COMMUNITY</span></div>
        </div>
        <div className="global-search">
          <Search size={18} />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Konularda ara..." />
          <kbd>⌘ K</kbd>
        </div>
        <div className="top-actions">
          <button className="icon-button notification-button" onClick={() => toast("3 yeni bildirimin var.")} aria-label="Bildirimler"><Bell size={19} /><span>3</span></button>
          <button className="user-chip" onClick={() => setShowProfile(true)}><Avatar initials="YA" color="#7c5cff" small /><span>Yasin A.</span><ChevronDown size={15} /></button>
        </div>
      </header>

      <div className="layout-grid">
        <aside className="sidebar">
          <div className="side-label">Çalışma alanı</div>
          <button className={`nav-item ${activeNav === "Forum" ? "active" : ""}`} onClick={() => { setActiveNav("Forum"); setActiveCategory("Tüm konular"); }}><MessageCircle size={18} />Forum <span className="nav-count">12</span></button>
          <button className={`nav-item ${activeNav === "Keşfet" ? "active" : ""}`} onClick={() => { setActiveNav("Keşfet"); setSort("En popüler"); }}><TrendingUp size={18} />Keşfet</button>
          <button className={`nav-item ${activeNav === "Kaydedilenler" ? "active" : ""}`} onClick={() => { setActiveNav("Kaydedilenler"); toast("Kaydedilen konular yakında burada."); }}><Bookmark size={18} />Kaydedilenler</button>
          <button className={`nav-item ${activeNav === "Rozetler" ? "active" : ""}`} onClick={() => setActiveNav("Rozetler")}><Trophy size={18} />Rozetler</button>
          <div className="side-divider" />
          <div className="side-label">Kanallar</div>
          {categories.slice(1).map(({ label, count, icon: Icon }) => (
            <button key={label} className={`nav-item channel-item ${activeCategory === label ? "active" : ""}`} onClick={() => { setActiveNav("Forum"); setActiveCategory(label); }}><Icon size={16} /><span>{label}</span><small>{count}</small></button>
          ))}
          <div className="sidebar-spacer" />
          <div className="upgrade-card">
            <div className="upgrade-icon"><Crown size={17} /></div>
            <strong>Topluluk Pro</strong>
            <p>Özel kanallara ve erken özelliklere eriş.</p>
            <button onClick={() => toast("Pro üyelik yakında aktif olacak.")}>Detayları gör <ChevronRight size={14} /></button>
          </div>
          <button className="nav-item settings-link" onClick={() => toast("Ayarlar yakında aktif olacak.")}><Settings2 size={17} />Ayarlar</button>
        </aside>

        <main className="main-content">
          {activeNav === "Rozetler" ? <BadgeShowcase /> : activeNav === "Admin" ? <AdminPanel /> : (
            <>
              <section className="welcome-row">
                <div>
                  <div className="eyebrow"><span className="status-dot" />TOPLULUK CANLI</div>
                  <h1>Günün gündemi <span>burada.</span></h1>
                  <p>Fikirlerini paylaş, sohbetlere katıl ve topluluğun nabzını tut.</p>
                </div>
                <button className="primary-button" onClick={() => setShowComposer(true)}><Plus size={18} />Yeni konu</button>
              </section>

              <section className="stats-strip">
                <div><strong>2.841</strong><span>toplam üye</span></div><div className="stats-divider" /><div><strong>128</strong><span>bugün aktif</span></div><div className="stats-divider" /><div><strong>46</strong><span>yeni konu</span></div><div className="stats-divider" /><div className="live-now"><span className="live-pulse" />18 kişi şimdi çevrimiçi</div>
              </section>

              <div className="content-columns">
                <section className="feed-column">
                  <div className="section-heading"><div><h2>{activeCategory}</h2><span>{filteredTopics.length} konu</span></div><div className="sort-select"><Clock3 size={15} /><select value={sort} onChange={(e) => setSort(e.target.value)}><option>Son aktiviteler</option><option>En çok konuşulan</option><option>En popüler</option></select><ChevronDown size={14} /></div></div>
                  <div className="filter-row"><button className={activeCategory === "Tüm konular" ? "selected" : ""} onClick={() => setActiveCategory("Tüm konular")}>Tümü</button><button onClick={() => setSort("En çok konuşulan")}>Çok konuşulan</button><button onClick={() => setSort("En popüler")}>Popüler</button><span className="filter-spacer" /><button className="filter-icon" onClick={() => toast("Gelişmiş filtreler yakında.")}><Tag size={15} /> Filtrele</button></div>
                  <div className="topic-list">
                    {filteredTopics.map((topic) => <TopicCard key={topic.id} topic={topic} liked={liked.includes(topic.id)} saved={saved.includes(topic.id)} onLike={() => toggleLike(topic.id)} onSave={() => toggleSave(topic.id)} onOpen={() => setSelectedTopic(topic)} />)}
                    {filteredTopics.length === 0 && <div className="empty-state"><Search size={30} /><strong>Sonuç bulunamadı</strong><p>Arama kelimeni veya kanal filtresini değiştirmeyi dene.</p></div>}
                  </div>
                </section>
                <aside className="right-rail">
                  <div className="rail-card profile-card"><div className="profile-card-top"><div><span className="eyebrow">PROFİLİM</span><h3>Yasin A.</h3><span className="muted">@yasin · 12 gündür burada</span></div><Avatar initials="YA" color="#7c5cff" /></div><div className="profile-level"><div><span>Topluluk seviyesi</span><strong>Gezgin <Zap size={14} fill="currentColor" /></strong></div><span className="level-score">248 / 500 XP</span></div><div className="progress-track"><span style={{ width: "49.6%" }} /></div><div className="mini-badges">{badgeList.slice(0, 3).map(({ icon: Icon, name, tone }) => <div className={`mini-badge ${tone}`} key={name}><Icon size={14} /><span>{name}</span></div>)}</div><button className="rail-link" onClick={() => setShowProfile(true)}>Profili görüntüle <ChevronRight size={15} /></button></div>
                  <div className="rail-card"><div className="rail-heading"><h3>Trend konular</h3><button onClick={() => { setSort("En popüler"); toast("Trend sıralaması uygulandı."); }}>Tümü</button></div>{topics.slice(0, 3).map((topic, index) => <button className="trend-item" key={topic.id} onClick={() => setSelectedTopic(topic)}><span className="trend-rank">0{index + 1}</span><span><strong>{topic.title}</strong><small>{topic.replies} yanıt · {topic.views} görüntülenme</small></span></button>)}</div>
                  <div className="rail-card online-card"><div className="rail-heading"><h3>Şu an aktif</h3><span className="online-count">18 çevrimiçi</span></div><div className="avatar-stack"><Avatar initials="MY" color="#7c5cff" small /><Avatar initials="EK" color="#ef6b8a" small /><Avatar initials="AD" color="#33c9a5" small /><Avatar initials="BÇ" color="#4e9bff" small /><span>+14</span></div><p>Topluluk bugün oldukça hareketli.</p></div>
                </aside>
              </div>
            </>
          )}
        </main>
      </div>

      <footer className="mobile-bottom-nav"><button className="active"><MessageCircle size={19} /><span>Forum</span></button><button onClick={() => setActiveNav("Keşfet")}><TrendingUp size={19} /><span>Keşfet</span></button><button onClick={() => setShowComposer(true)} className="mobile-add"><Plus size={21} /></button><button onClick={() => setActiveNav("Rozetler")}><Trophy size={19} /><span>Rozetler</span></button><button onClick={() => setShowProfile(true)}><Avatar initials="YA" color="#7c5cff" small /><span>Profil</span></button></footer>

      {showComposer && <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && setShowComposer(false)}><div className="composer-modal"><div className="modal-heading"><div><span className="eyebrow">TOPLULUĞA KATIL</span><h2>Yeni konu oluştur</h2></div><button className="close-button" onClick={() => setShowComposer(false)}><X size={19} /></button></div><label>Başlık<input autoFocus value={newTitle} onChange={(e) => setNewTitle(e.target.value)} placeholder="Konunu tek cümlede anlat..." /></label><label>Kanal<select value={newCategory} onChange={(e) => setNewCategory(e.target.value)}>{categories.slice(1).map((category) => <option key={category.label}>{category.label}</option>)}</select></label><label>İçerik<textarea value={newBody} onChange={(e) => setNewBody(e.target.value)} placeholder="Düşüncelerini, sorunu veya hikâyeni paylaş..." rows={5} /></label><div className="composer-footer"><span><CircleHelp size={15} /> Saygılı ve yapıcı kalalım.</span><button className="primary-button" onClick={createTopic}><PenLine size={16} />Konuyu yayınla</button></div></div></div>}
      {selectedTopic && <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && setSelectedTopic(null)}><div className="topic-modal"><div className="modal-heading"><div className="topic-modal-meta"><BadgePill name={selectedTopic.category} /><span>{selectedTopic.time}</span></div><button className="close-button" onClick={() => setSelectedTopic(null)}><X size={19} /></button></div><h2>{selectedTopic.title}</h2><div className="author-row"><Avatar initials={selectedTopic.initials} color={selectedTopic.color} small /><div><strong>{selectedTopic.author}</strong><span>{selectedTopic.handle} · <BadgePill name={selectedTopic.badge} /></span></div></div><p className="topic-modal-body">{selectedTopic.body}</p><div className="topic-modal-tags">{selectedTopic.tags.map((tag) => <span key={tag}>{tag}</span>)}</div><div className="modal-actions"><button className={liked.includes(selectedTopic.id) ? "liked" : ""} onClick={() => toggleLike(selectedTopic.id)}><ThumbsUp size={17} />{selectedTopic.likes + (liked.includes(selectedTopic.id) ? 1 : 0)} beğeni</button><button onClick={() => toast("Yanıt editörü yakında aktif olacak.")}><MessageCircle size={17} />{selectedTopic.replies} yanıt</button><button onClick={() => toggleSave(selectedTopic.id)}><Bookmark size={17} />Kaydet</button></div><div className="reply-placeholder"><Avatar initials="YA" color="#7c5cff" small /><input placeholder="Bu konuya yanıt yaz..." onClick={() => toast("Yanıt editörü yakında aktif olacak.")} /></div></div></div>}
      {showProfile && <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && setShowProfile(false)}><div className="profile-modal"><div className="profile-cover" /><button className="close-button profile-close" onClick={() => setShowProfile(false)}><X size={19} /></button><div className="profile-modal-content"><Avatar initials="YA" color="#7c5cff" /><h2>Yasin A.</h2><span className="muted">@yasin · App Crypto 24 topluluk üyesi</span><div className="profile-stats"><div><strong>24</strong><span>konu</span></div><div><strong>148</strong><span>yanıt</span></div><div><strong>248</strong><span>XP</span></div></div><div className="profile-badges"><h3>Kazanılan rozetler</h3>{badgeList.map(({ icon: Icon, name, detail, tone }) => <div className="profile-badge-row" key={name}><span className={`mini-badge ${tone}`}><Icon size={16} /></span><span><strong>{name}</strong><small>{detail}</small></span><CheckCircle2 size={17} className="check-icon" /></div>)}</div><button className="secondary-button" onClick={() => { setShowProfile(false); setActiveNav("Admin"); }}>Admin panelini görüntüle <ShieldCheck size={16} /></button></div></div></div>}
    </div>
  );
}

function TopicCard({ topic, liked, saved, onLike, onSave, onOpen }: { topic: Topic; liked: boolean; saved: boolean; onLike: () => void; onSave: () => void; onOpen: () => void }) {
  return <article className="topic-card"><div className="topic-main"><button className="topic-click-area" onClick={onOpen}><div className="topic-topline">{topic.pinned && <span className="topic-flag pinned"><Pin size={12} />Sabitlendi</span>}{topic.hot && <span className="topic-flag hot"><Flame size={12} />Trend</span>}{topic.solved && <span className="topic-flag solved"><CheckCircle2 size={12} />Çözüldü</span>}<span className="topic-category">{topic.category}</span></div><h3>{topic.title}</h3><p>{topic.body}</p><div className="topic-tags">{topic.tags.map((tag) => <span key={tag}>{tag}</span>)}</div></button><div className="author-row"><Avatar initials={topic.initials} color={topic.color} small /><div><strong>{topic.author}</strong><span>{topic.handle} · {topic.time} · <BadgePill name={topic.badge} /></span></div></div></div><div className="topic-side"><div className="topic-metric"><strong>{topic.replies}</strong><span>yanıt</span></div><div className="topic-metric"><strong>{topic.views.toLocaleString("tr-TR")}</strong><span>görüntülenme</span></div><div className="topic-actions"><button className={liked ? "liked" : ""} onClick={onLike} aria-label="Beğen"><ThumbsUp size={16} /><span>{topic.likes + (liked ? 1 : 0)}</span></button><button className={saved ? "saved" : ""} onClick={onSave} aria-label="Kaydet"><Bookmark size={16} /></button><button onClick={() => toast("Konu seçenekleri yakında.")} aria-label="Daha fazla"><MoreHorizontal size={17} /></button></div></div></article>;
}

function BadgeShowcase() {
  return <section className="special-page"><div className="eyebrow"><Trophy size={15} />KATILIMI GÖRÜNÜR KIL</div><h1>Rozet koleksiyonun</h1><p className="special-lead">Topluluğa kattığın değer, kazandığın rozetlerle görünür.</p><div className="badge-hero"><div className="badge-hero-orb"><Crown size={42} /></div><div><span className="eyebrow">MEVCUT SEVİYE</span><h2>Gezgin <span>· 248 XP</span></h2><p>Bir sonraki seviyeye 252 XP kaldı. Konu açmaya devam et.</p><div className="progress-track"><span style={{ width: "49.6%" }} /></div></div></div><div className="badge-grid">{badgeList.map(({ icon: Icon, name, detail, tone }) => <div className={`badge-large ${tone}`} key={name}><div className="badge-large-icon"><Icon size={27} /></div><h3>{name}</h3><p>{detail}</p><span className="earned"><CheckCircle2 size={14} />Kazanıldı</span></div>)}</div></section>;
}

function downloadCsv(filename: string, rows: Record<string, unknown>[]) {
  if (!rows.length) {
    toast("Dışa aktarılacak veri bulunamadı.");
    return;
  }
  const columns = Object.keys(rows[0]);
  const escapeCsv = (value: unknown) => {
    const normalized = value === null || value === undefined ? "" : String(value);
    return /[",\n\r]/.test(normalized) ? `"${normalized.replace(/"/g, '""')}"` : normalized;
  };
  const csv = [columns, ...rows.map((row) => columns.map((column) => escapeCsv(row[column])))]
    .map((line) => line.join(","))
    .join("\r\n");
  const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function AdminPanel() {
  const [period, setPeriod] = useState<"7" | "30" | "90">("30");
  const [metric, setMetric] = useState<"members" | "activity" | "content">("activity");
  const [channel, setChannel] = useState("Tümü");
  const [userStatus, setUserStatus] = useState("Tüm durumlar");
  const [memberQuery, setMemberQuery] = useState("");
  const [showFilters, setShowFilters] = useState(true);
  const [isExporting, setIsExporting] = useState(false);

  const chartData = useMemo(() => {
    const channelWeight = channel === "Tümü" ? 1 : channel === "Maç sohbeti" ? 1.12 : channel === "Transfer merkezi" ? .88 : .74;
    return activityData[period].map((point) => ({
      ...point,
      replies: Math.round(point.replies * channelWeight),
      topics: Math.round(point.topics * channelWeight),
      users: Math.round(point.users * (channel === "Tümü" ? 1 : .72)),
    }));
  }, [channel, period]);

  const metricKey = metric === "members" ? "users" : metric === "content" ? "topics" : "replies";
  const metricLabel = metric === "members" ? "aktif kullanıcı" : metric === "content" ? "yeni konu" : "yanıt";
  const metricColor = metric === "members" ? "#54d7d0" : metric === "content" ? "#f1bd61" : "#8d72ff";
  const filteredMembers = useMemo(() => memberRows.filter((member) => {
    const queryMatch = !memberQuery || `${member.name} ${member.role}`.toLocaleLowerCase("tr-TR").includes(memberQuery.toLocaleLowerCase("tr-TR"));
    const statusMatch = userStatus === "Tüm durumlar" || member.status === userStatus;
    return queryMatch && statusMatch;
  }), [memberQuery, userStatus]);
  const totalSegments = userSegments.reduce((sum, segment) => sum + segment.value, 0);

  const exportMemberRows = filteredMembers.map((member) => ({
    Kullanıcı: member.name,
    Rol: member.role,
    Durum: member.status,
    Konu: member.topics,
    Yanıt: member.replies,
    SonAktivite: member.lastActive,
  }));
  const exportActivityRows = chartData.map((point) => ({
    Dönem: point.day,
    AktifKullanıcı: point.users,
    Yanıt: point.replies,
    YeniKonu: point.topics,
    Görüntülenme: point.views,
  }));
  const exportChannelRows = channelActivity.map((item) => ({
    Kanal: item.name,
    Konu: item.topics,
    Yanıt: item.replies,
  }));
  const exportSegmentRows = userSegments.map((segment) => ({
    Segment: segment.name,
    Kullanıcı: segment.value,
    Oran: `${Math.round(segment.value / totalSegments * 100)}%`,
  }));
  const exportSuffix = `${period}gun-${new Date().toISOString().slice(0, 10)}`;
  const handleCsvExport = () => {
    downloadCsv(`macweb-kullanicilar-${exportSuffix}.csv`, exportMemberRows);
    toast(`${exportMemberRows.length} kullanıcı CSV olarak indirildi.`);
  };
  const handleExcelExport = () => {
    setIsExporting(true);
    try {
      const workbook = XLSX.utils.book_new();
      const summaryRows = [
        { Alan: "Rapor tarihi", Değer: new Date().toLocaleString("tr-TR") },
        { Alan: "Dönem", Değer: `${period} gün` },
        { Alan: "Kanal filtresi", Değer: channel },
        { Alan: "Kullanıcı durumu", Değer: userStatus },
        { Alan: "Üye araması", Değer: memberQuery || "Yok" },
        { Alan: "Aktif üye", Değer: 2841 },
        { Alan: "Toplam konu", Değer: 4892 },
        { Alan: "Filtrelenmiş kullanıcı", Değer: exportMemberRows.length },
      ];
      const sheets = [
        ["Özet", summaryRows],
        ["Kullanıcılar", exportMemberRows],
        ["Aktivite", exportActivityRows],
        ["Kanallar", exportChannelRows],
        ["Segmentler", exportSegmentRows],
      ] as const;
      sheets.forEach(([name, rows]) => {
        const sheet = XLSX.utils.json_to_sheet(rows);
        sheet["!cols"] = Object.keys(rows[0] || {}).map(() => ({ wch: 20 }));
        XLSX.utils.book_append_sheet(workbook, sheet, name);
      });
      XLSX.writeFile(workbook, `macweb-admin-raporu-${exportSuffix}.xlsx`);
      toast("Excel raporu 5 çalışma sayfasıyla indirildi.");
    } finally {
      setIsExporting(false);
    }
  };

  return <section className="special-page admin-page">
    <div className="admin-header"><div><div className="eyebrow"><ShieldCheck size={15} />YÖNETİM MERKEZİ</div><h1>Topluluğu yönet</h1><p className="special-lead">Moderasyon, üyeler ve içerik sağlığı tek ekranda.</p></div><span className="admin-status"><span className="status-dot" /> Sistemler normal</span></div>

    <div className="admin-stats"><div><span>İncelenecek rapor</span><strong>08</strong><small>son 24 saatte +2</small></div><div><span>Aktif üye</span><strong>2.841</strong><small className="positive">+12.4% bu hafta</small></div><div><span>Toplam konu</span><strong>4.892</strong><small className="positive">+46 bugün</small></div><div><span>Yanıt süresi</span><strong>6 dk</strong><small className="positive">hedef içinde</small></div></div>

    <div className="analytics-toolbar">
      <div><div className="eyebrow"><BarChart3 size={14} />ANALİTİK ÖZET</div><strong>Topluluk performansı</strong><span>Filtrelere göre canlı güncellenir</span></div>
      <div className="analytics-toolbar-actions"><button className={showFilters ? "active" : ""} onClick={() => setShowFilters((value) => !value)}><SlidersHorizontal size={15} />Filtreler</button><button onClick={handleCsvExport} disabled={isExporting}><Download size={15} />CSV</button><button onClick={handleExcelExport} disabled={isExporting}><FileSpreadsheet size={15} />{isExporting ? "Hazırlanıyor" : "Excel"}</button><button onClick={() => toast("Veriler yenilendi.")} aria-label="Yenile"><RefreshCw size={15} /></button></div>
    </div>

    {showFilters && <div className="advanced-filters"><div className="filter-control"><label>Dönem</label><div className="segmented-control">{([["7", "7 gün"], ["30", "30 gün"], ["90", "90 gün"]] as const).map(([value, label]) => <button key={value} className={period === value ? "selected" : ""} onClick={() => setPeriod(value)}>{label}</button>)}</div></div><div className="filter-control"><label>Grafik metriği</label><select value={metric} onChange={(event) => setMetric(event.target.value as typeof metric)}><option value="activity">Yanıt aktivitesi</option><option value="members">Aktif kullanıcı</option><option value="content">Yeni konular</option></select></div><div className="filter-control"><label>Kanal</label><select value={channel} onChange={(event) => setChannel(event.target.value)}><option>Tümü</option>{channelActivity.map((item) => <option key={item.name}>{item.name}</option>)}</select></div><div className="filter-control"><label>Kullanıcı durumu</label><select value={userStatus} onChange={(event) => setUserStatus(event.target.value)}><option>Tüm durumlar</option><option>Aktif</option><option>Uzakta</option></select></div></div>}

    <div className="analytics-grid"><div className="analytics-card activity-chart-card"><div className="analytics-card-heading"><div><h3><Activity size={16} /> Aktivite trendi</h3><p>{channel === "Tümü" ? "Tüm kanallar" : channel} · son {period} gün</p></div><span className="chart-highlight" style={{ color: metricColor }}><strong>{chartData.reduce((sum, point) => sum + point[metricKey], 0).toLocaleString("tr-TR")}</strong> {metricLabel}</span></div><div className="chart-wrap"><ResponsiveContainer width="100%" height={255}><AreaChart data={chartData} margin={{ top: 8, right: 5, left: -22, bottom: 0 }}><defs><linearGradient id="activityGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={metricColor} stopOpacity={.38} /><stop offset="100%" stopColor={metricColor} stopOpacity={0} /></linearGradient></defs><CartesianGrid stroke="rgba(170,177,232,.1)" vertical={false} /><XAxis dataKey="day" axisLine={false} tickLine={false} tick={{ fill: "#747b98", fontSize: 10 }} /><YAxis axisLine={false} tickLine={false} tick={{ fill: "#747b98", fontSize: 10 }} /><ChartTooltip contentStyle={{ background: "#171a2e", border: "1px solid rgba(141,114,255,.32)", borderRadius: 9, color: "#eef0ff", fontSize: 11 }} labelStyle={{ color: "#aaa0e9" }} /><Area type="monotone" dataKey={metricKey} stroke={metricColor} fill="url(#activityGradient)" strokeWidth={2.5} dot={{ fill: metricColor, strokeWidth: 0, r: 3 }} activeDot={{ r: 5, stroke: "#fff", strokeWidth: 2 }} /></AreaChart></ResponsiveContainer></div><div className="chart-legend"><span><i style={{ background: metricColor }} />{metricLabel}</span><span><i style={{ background: "#3a3f5b" }} />Önceki dönem ile karşılaştırmalı</span></div></div><div className="analytics-card segment-card"><div className="analytics-card-heading"><div><h3><UsersRound size={16} /> Kullanıcı dağılımı</h3><p>Seçili dönemdeki görünüm</p></div><span className="segment-total">{totalSegments} kişi</span></div><div className="donut-wrap"><ResponsiveContainer width="100%" height={155}><PieChart><Pie data={userSegments} dataKey="value" nameKey="name" innerRadius={48} outerRadius={68} paddingAngle={4} stroke="none">{userSegments.map((segment) => <Cell key={segment.name} fill={segment.color} />)}</Pie><ChartTooltip contentStyle={{ background: "#171a2e", border: "1px solid rgba(141,114,255,.32)", borderRadius: 9, color: "#eef0ff", fontSize: 11 }} /></PieChart></ResponsiveContainer><div className="donut-center"><strong>240</strong><span>üye</span></div></div><div className="segment-list">{userSegments.map((segment) => <div key={segment.name}><span><i style={{ background: segment.color }} />{segment.name}</span><strong>{segment.value}<small>{Math.round(segment.value / totalSegments * 100)}%</small></strong></div>)}</div></div></div>

    <div className="analytics-grid lower-analytics"><div className="analytics-card channel-chart-card"><div className="analytics-card-heading"><div><h3><Hash size={16} /> Kanal etkileşimi</h3><p>Konu ve yanıt yoğunluğu</p></div><span className="chart-highlight"><strong>{channelActivity.reduce((sum, item) => sum + item.replies, 0).toLocaleString("tr-TR")}</strong> yanıt</span></div><div className="chart-wrap"><ResponsiveContainer width="100%" height={210}><BarChart data={channelActivity} layout="vertical" margin={{ top: 2, right: 7, left: 12, bottom: 0 }}><CartesianGrid stroke="rgba(170,177,232,.1)" horizontal={false} /><XAxis type="number" axisLine={false} tickLine={false} tick={{ fill: "#747b98", fontSize: 10 }} /><YAxis type="category" dataKey="name" width={105} axisLine={false} tickLine={false} tick={{ fill: "#9ca3bd", fontSize: 10 }} /><ChartTooltip cursor={{ fill: "rgba(141,114,255,.08)" }} contentStyle={{ background: "#171a2e", border: "1px solid rgba(141,114,255,.32)", borderRadius: 9, color: "#eef0ff", fontSize: 11 }} /><Bar dataKey="replies" fill="#8d72ff" radius={[0, 5, 5, 0]} barSize={13} /></BarChart></ResponsiveContainer></div></div><div className="analytics-card member-table-card"><div className="analytics-card-heading"><div><h3><Users size={16} /> En aktif üyeler</h3><p>{filteredMembers.length} kullanıcı listeleniyor</p></div><button className="text-action" onClick={() => toast("Üye yönetimi açıldı.")}>Yönet</button></div><div className="member-table">{filteredMembers.map((member) => <div className="member-row" key={member.name}><Avatar initials={member.initials} color={member.color} small /><span className="member-name"><strong>{member.name}</strong><small>{member.role}</small></span><span className="member-activity"><strong>{member.replies}</strong><small>yanıt</small></span><span className={`member-status ${member.status === "Aktif" ? "online" : "away"}`}><i />{member.status}</span></div>)}{filteredMembers.length === 0 && <div className="member-empty">Filtreye uygun üye bulunamadı.</div>}</div></div></div>

    <div className="admin-grid"><div className="admin-card"><div className="rail-heading"><h3>Moderasyon kuyruğu</h3><button onClick={() => toast("Tüm raporlar açıldı.")}>Tümünü gör</button></div>{["Spam bağlantı bildirimi", "Uygunsuz dil bildirimi", "Tekrarlanan konu"].map((item, i) => <div className="moderation-row" key={item}><div className={`moderation-icon ${i === 1 ? "warning" : ""}`}><Flag size={16} /></div><span><strong>{item}</strong><small>{i + 1} yeni rapor · {i + 4} dk önce</small></span><button onClick={() => toast("Rapor incelemeye alındı.")}><ChevronRight size={17} /></button></div>)}</div><div className="admin-card"><div className="rail-heading"><h3>Hızlı işlemler</h3></div><div className="quick-actions"><button onClick={() => toast("Yeni kanal sihirbazı açıldı.")}><Plus size={18} /><span>Yeni kanal oluştur</span><ChevronRight size={16} /></button><button onClick={() => toast("Rozet düzenleyici açıldı.")}><Trophy size={18} /><span>Rozetleri düzenle</span><ChevronRight size={16} /></button><button onClick={() => toast("Duyuru editörü açıldı.")}><Bell size={18} /><span>Duyuru yayınla</span><ChevronRight size={16} /></button></div></div></div>
  </section>;
}
