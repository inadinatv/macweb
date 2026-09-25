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
} from "lucide-react";
import { toast } from "sonner";

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

function AdminPanel() {
  return <section className="special-page admin-page"><div className="admin-header"><div><div className="eyebrow"><ShieldCheck size={15} />YÖNETİM MERKEZİ</div><h1>Topluluğu yönet</h1><p className="special-lead">Moderasyon, üyeler ve içerik sağlığı tek ekranda.</p></div><span className="admin-status"><span className="status-dot" /> Sistemler normal</span></div><div className="admin-stats"><div><span>İncelenecek rapor</span><strong>08</strong><small>son 24 saatte +2</small></div><div><span>Aktif üye</span><strong>2.841</strong><small className="positive">+12.4% bu hafta</small></div><div><span>Toplam konu</span><strong>4.892</strong><small className="positive">+46 bugün</small></div><div><span>Yanıt süresi</span><strong>6 dk</strong><small className="positive">hedef içinde</small></div></div><div className="admin-grid"><div className="admin-card"><div className="rail-heading"><h3>Moderasyon kuyruğu</h3><button onClick={() => toast("Tüm raporlar açıldı.")}>Tümünü gör</button></div>{["Spam bağlantı bildirimi", "Uygunsuz dil bildirimi", "Tekrarlanan konu"].map((item, i) => <div className="moderation-row" key={item}><div className={`moderation-icon ${i === 1 ? "warning" : ""}`}><Flag size={16} /></div><span><strong>{item}</strong><small>{i + 1} yeni rapor · {i + 4} dk önce</small></span><button onClick={() => toast("Rapor incelemeye alındı.")}><ChevronRight size={17} /></button></div>)}</div><div className="admin-card"><div className="rail-heading"><h3>Hızlı işlemler</h3></div><div className="quick-actions"><button onClick={() => toast("Yeni kanal sihirbazı açıldı.")}><Plus size={18} /><span>Yeni kanal oluştur</span><ChevronRight size={16} /></button><button onClick={() => toast("Rozet düzenleyici açıldı.")}><Trophy size={18} /><span>Rozetleri düzenle</span><ChevronRight size={16} /></button><button onClick={() => toast("Duyuru editörü açıldı.")}><Bell size={18} /><span>Duyuru yayınla</span><ChevronRight size={16} /></button></div></div></div></section>;
}
